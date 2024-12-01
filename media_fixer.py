#!/usr/bin/env python3
"""
Media Fixer - Convert videos to preferred container, codec and sizing
By Willy Gardiol, provided under the GPLv3 License.
https://www.gnu.org/licenses/gpl-3.0.html
Publicly available at: https://github.com/gardiol/media_fixer
Contact: willy@gardiol.org

Python Version:
By Kieran Bicheno, provided under the GPLv3 License.
https://www.gnu.org/licenses/gpl-3.0.html
Publicly available at: https://github.com/TheLustriVA/media_fixer
Contact: thelustriva@gmail.com
"""

import argparse
import logging
import os
import pathlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from pymediainfo import MediaInfo
from tqdm import tqdm
import time
import queue
import threading

@dataclass
class ConversionConfig:
    """Holds configuration for media conversion"""
    container: str
    container_extension: str
    video_codec: str
    video_width: int
    video_height: int
    ffmpeg_extra_opts: str
    ffmpeg_encode: str
    ffmpeg_resize: str

class QueueManager:
    """Manages the various queue files for video processing"""
    def __init__(self, queue_path: str, prefix: str = ""):
        self.queue_path = pathlib.Path(queue_path)
        self.prefix = prefix
        self.queues = {
            'skipped': self._get_queue_file('skipped'),
            'failed': self._get_queue_file('failed'),
            'completed': self._get_queue_file('completed'),
            'in_progress': self._get_queue_file('in_progress'),
            'leftovers': self._get_queue_file('leftovers')
        }

    def _get_queue_file(self, name: str) -> pathlib.Path:
        return self.queue_path / f"{self.prefix}mediafixer_queue.{name}"

    def initialize_queues(self):
        """Create empty queue files"""
        for queue_file in self.queues.values():
            queue_file.write_text('')

    def add_to_queue(self, queue_name: str, entry: str):
        """Add an entry to specified queue"""
        with open(self.queues[queue_name], 'a') as f:
            f.write(f"{entry}\n")

    def get_queue_length(self, queue_name: str) -> int:
        """Get number of entries in specified queue"""
        try:
            if queue_name not in self.queues:
                return 0
            with open(self.queues[queue_name]) as f:
                return sum(1 for _ in f)
        except FileNotFoundError:
            return 0

    def pop_from_queue(self, queue_name: str) -> Optional[str]:
        """Remove and return first entry from specified queue"""
        try:
            with open(self.queues[queue_name]) as f:
                lines = f.readlines()
            if not lines:
                return None
            with open(self.queues[queue_name], 'w') as f:
                f.writelines(lines[1:])
            return lines[0].strip()
        except FileNotFoundError:
            return None

class MediaFixer:
    def __init__(self):
        self.mediainfo_exe = shutil.which('mediainfo')
        self.ffmpeg_exe = shutil.which('ffmpeg')
        
        if not self.mediainfo_exe:
            raise RuntimeError("Missing 'mediainfo' executable. Please install the mediainfo package.")
        if not self.ffmpeg_exe:
            raise RuntimeError("Missing 'ffmpeg' executable. Please install the ffmpeg package.")
            
        # Initialize configuration from environment or defaults
        self.config = ConversionConfig(
            # Container settings
            container=os.environ.get('MEDIAFIXER_CONTAINER', 'Matroska'),
            container_extension=os.environ.get('MEDIAFIXER_CONTAINER_EXTENSION', 'mkv'),
            
            # Video settings
            video_codec=os.environ.get('MEDIAFIXER_VIDEO_CODEC', 'AV1'),
            video_width=int(os.environ.get('MEDIAFIXER_VIDEO_WIDTH', '1280')),
            video_height=int(os.environ.get('MEDIAFIXER_VIDEO_HEIGHT', '720')),
            
            # FFmpeg settings
            ffmpeg_extra_opts=os.environ.get('MEDIAFIXER_FFMPEG_EXTRA_OPTS', 
                '-fflags +genpts -nostdin -find_stream_info'),
            
            # Encoding settings with expanded options
            ffmpeg_encode=os.environ.get('MEDIAFIXER_FFMPEG_ENCODE', 
                '-c:v libsvtav1 -crf 38 -preset 8 -g 240 -pix_fmt yuv420p ' + 
                '-map 0 -map -0:d -c:a copy -c:s copy'),
            
            # Resize settings with variable interpolation
            ffmpeg_resize=os.environ.get('MEDIAFIXER_FFMPEG_RESIZE', 
                '-vf "scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT}:flags=lanczos,' +
                'format=yuv420p"')
        )
        
        self.logger = logging.getLogger('MediaFixer')
        self.test_only = False

    def setup_logging(self, log_file: str, test_only: bool = False):
        """Configure logging to both file and console"""
        self.logger.setLevel(logging.DEBUG)
        self.test_only = test_only
        
        # File handler
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        
        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # Formatting
        formatter = logging.Formatter('%(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)
        
        if test_only:
            self.logger.info("Running in TEST mode")

    def analyze_video(self, filepath: str) -> Tuple[int, bool, bool, bool]:
        """
        Analyze video file and determine needed conversions
        Returns: (result, needs_container, needs_encode, needs_resize)
        result: 0=failed, 1=needs work, 2=skip
        """
        try:
            media_info = MediaInfo.parse(filepath)
            video_track = next((track for track in media_info.tracks 
                              if track.track_type == "Video"), None)
            general_track = next((track for track in media_info.tracks 
                                if track.track_type == "General"), None)

            if not video_track or not general_track:
                self.logger.error(f"Unable to parse video information for {filepath}")
                return 0, False, False, False

            needs_container = general_track.format != self.config.container
            needs_encode = video_track.format != self.config.video_codec
            needs_resize = (video_track.height and 
                          int(video_track.height) > self.config.video_height)

            if needs_container or needs_encode or needs_resize:
                return 1, needs_container, needs_encode, needs_resize
            return 2, False, False, False

        except Exception as e:
            self.logger.error(f"Error analyzing {filepath}: {e}")
            return 0, False, False, False

    def process_video(self, filepath: str, needs_container: bool, 
                     needs_encode: bool, needs_resize: bool) -> bool:
        """
        Process a single video file according to needed conversions
        Returns: True if successful, False otherwise
        """
        try:
            path = pathlib.Path(filepath)
            working_file = path.with_name(f"{path.stem}.mediafixer_working")
            
            # Copy original to working file
            if not self.test_only:
                shutil.copy2(filepath, working_file)

            if needs_container:
                success = self._transmux_video(working_file)
                if not success:
                    return False

            if needs_encode or needs_resize:
                success = self._encode_video(working_file, needs_encode, needs_resize)
                if not success:
                    return False

            # Move to final destination
            if not self.test_only:
                final_path = path.with_suffix(f".{self.config.container_extension}")
                working_file.rename(final_path)
                if final_path != path:
                    path.unlink()

            return True

        except Exception as e:
            self.logger.error(f"Error processing {filepath}: {e}")
            return False

    def _transmux_video(self, filepath: pathlib.Path) -> bool:
        """Transmux video to new container format"""
        try:
            if self.test_only:
                return True
                
            output = filepath.with_name(f"{filepath.stem}.tmuxed.{self.config.container_extension}")
            cmd = [
                self.ffmpeg_exe, "-fflags", "+genpts", "-nostdin",
                "-find_stream_info", "-i", str(filepath),
                "-map", "0", "-map", "-0:d", "-codec", "copy",
                "-codec:s", "srt", str(output)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                output.replace(filepath)
                return True
            else:
                self.logger.error(f"FFmpeg transmux error: {result.stderr}")
                if output.exists():
                    output.unlink()
                return False

        except Exception as e:
            self.logger.error(f"Transmux error: {e}")
            return False

    def _encode_video(self, filepath: pathlib.Path, 
                     needs_encode: bool, needs_resize: bool) -> bool:
        """Encode/resize video with enhanced FFmpeg control"""
        try:
            if self.test_only:
                return True
                
            output = filepath.with_name(f"{filepath.stem}.encoded.{self.config.container_extension}")
            
            # Base command with input
            cmd = [self.ffmpeg_exe]
            cmd.extend(self.config.ffmpeg_extra_opts.split())
            cmd.extend(["-i", str(filepath)])
            
            # Handle encoding options
            if needs_encode:
                cmd.extend(["-c:v", "libx264"])  # Use H.264 instead of AV1
                cmd.extend(["-crf", "23"])  # Standard quality
            else:
                cmd.extend(["-c:v", "copy"])
            
            # Handle resize options
            if needs_resize:
                cmd.extend(["-vf", f"scale={self.config.video_width}:{self.config.video_height}"])
            
            # Add common options
            cmd.extend(["-c:a", "copy", "-c:s", "copy"])
            
            # Output file
            cmd.append(str(output))
            
            self.logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                output.replace(filepath)
                return True
            else:
                self.logger.error(f"FFmpeg encode error: {result.stderr}")
                if output.exists():
                    output.unlink()
                return False

        except Exception as e:
            self.logger.error(f"Encode error: {e}")
            return False

    def scan_videos(self, start_path: str, queue_manager: QueueManager):
        """Scan directory for video files and queue them for processing"""
        start_path = pathlib.Path(start_path)
        
        def is_video_file(filepath: str) -> bool:
            try:
                result = subprocess.run(
                    ["file", "--mime-type", filepath],
                    capture_output=True, text=True
                )
                return "video/" in result.stdout
            except Exception:
                return False

        for filepath in tqdm(list(start_path.rglob("*")), desc="Scanning files"):
            if not filepath.is_file():
                continue
                
            str_path = str(filepath)
            if str_path.endswith("mediafixer_working"):
                if self.test_only:
                    self.logger.info(f"Would delete temp file: {str_path}")
                else:
                    filepath.unlink()
                    self.logger.info(f"Deleted temp file: {str_path}")
                continue

            if is_video_file(str_path):
                result, needs_container, needs_encode, needs_resize = self.analyze_video(str_path)
                
                if result == 0:
                    queue_manager.add_to_queue('failed', str_path)
                elif result == 2:
                    queue_manager.add_to_queue('skipped', str_path)
                else:
                    entry = f"{str_path}|||| {needs_container} {needs_encode} {needs_resize}"
                    queue_manager.add_to_queue('in_progress', entry)

def main():
    parser = argparse.ArgumentParser(
        description="Media Fixer - Reconvert videos to preferred container, codec and sizing"
    )
    parser.add_argument('-l', '--logfile', help='Log file path')
    parser.add_argument('-a', action='store_true', help='Start from current folder')
    parser.add_argument('-p', '--path', help='Start path for scanning')
    parser.add_argument('-q', '--queue-path', help='Queue files storage path')
    parser.add_argument('-r', '--prefix', help='Queue filename prefix')
    parser.add_argument('-t', '--test', action='store_true', help='Test mode')
    parser.add_argument('-f', '--force', action='store_true', help='Force queue analysis')
    parser.add_argument('-d', '--delete-temp', action='store_true', help='Delete old temporary files')
    parser.add_argument('-x', '--retry-failed', action='store_true', help='Retry failed conversions')
    parser.add_argument('-s', '--clean-only', action='store_true', help='Only clean stale files')
    parser.add_argument('-i', '--interactive', action='store_true', help='Interactive mode')
    
    args = parser.parse_args()
    
    if not (args.a or args.path) and not args.clean_only:
        parser.error("Either -a or -p must be specified unless using -s")
        
    try:
        scan_path = args.path if args.path else os.getcwd()
        queue_path = args.queue_path if args.queue_path else scan_path
        log_file = args.logfile if args.logfile else os.path.join(scan_path, "mediafixer.log")
        
        fixer = MediaFixer()
        fixer.setup_logging(log_file, args.test)
        queue_manager = QueueManager(queue_path, args.prefix or "")
        
        if args.force or not queue_manager.get_queue_length('in_progress'):
            queue_manager.initialize_queues()
            
            if args.retry_failed:
                failed_entries = []
                while True:
                    entry = queue_manager.pop_from_queue('failed')
                    if not entry:
                        break
                    failed_entries.append(entry)
                
                for entry in failed_entries:
                    queue_manager.add_to_queue('in_progress', entry)
                    
            if not args.clean_only:
                fixer.scan_videos(scan_path, queue_manager)
                
        if args.clean_only:
            fixer.logger.info("Only cleaning temporary files: terminating operations.")
            sys.exit(0)
            
        total_work = queue_manager.get_queue_length('in_progress')
        fixer.logger.info(f"Failed queue has {queue_manager.get_queue_length('failed')} videos.")
        fixer.logger.info(f"Skipped queue has {queue_manager.get_queue_length('skipped')} videos.")
        fixer.logger.info(f"Work queue has {total_work} videos to be processed...")
        
        if args.interactive:
            input("Ready to go? Press RETURN to start, or CTRL+C to abort.")
            
        work_count = 1
        while True:
            entry = queue_manager.pop_from_queue('in_progress')
            if not entry:
                break
                
            filepath, flags = entry.split('||||')
            filepath = filepath.strip()
            needs_container, needs_encode, needs_resize = map(lambda x: x.strip() == 'True', 
                                                            flags.strip().split())
            
            fixer.logger.info(f"--- Processing video '{filepath}' [ {work_count} / {total_work} ]")
            work_count += 1
            
            if needs_container or needs_encode or needs_resize:
                success = fixer.process_video(filepath, needs_container, needs_encode, needs_resize)
                queue_name = 'completed' if success else 'failed'
                queue_manager.add_to_queue(queue_name, entry)
            
        fixer.logger.info("All done.")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
