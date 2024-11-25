#!/usr/bin/env python3
"""
Media Fixer - Convert videos to preferred container, codec and sizing
By Willy Gardiol, provided under the GPLv3 License.
https://www.gnu.org/licenses/gpl-3.0.html
Publicly available at: https://github.com/gardiol/media_fixer
Contact: willy@gardiol.org
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
            container=os.environ.get('MEDIAFIXER_CONTAINER', 'Matroska'),
            container_extension=os.environ.get('MEDIAFIXER_CONTAINER_EXTENSION', 'mkv'),
            video_codec=os.environ.get('MEDIAFIXER_VIDEO_CODEC', 'AV1'),
            video_width=int(os.environ.get('MEDIAFIXER_VIDEO_WIDTH', '1280')),
            video_height=int(os.environ.get('MEDIAFIXER_VIDEO_HEIGHT', '720')),
            ffmpeg_extra_opts=os.environ.get('MEDIAFIXER_FFMPEG_EXTRA_OPTS', '-fflags +genpts'),
            ffmpeg_encode=os.environ.get('MEDIAFIXER_FFMPEG_ENCODE', '-c:v libsvtav1 -crf 38'),
            ffmpeg_resize=os.environ.get('MEDIAFIXER_FFMPEG_RESIZE', '-vf scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT}')
        )
        
        self.logger = logging.getLogger('MediaFixer')

    def setup_logging(self, log_file: str, test_only: bool = False):
        """Configure logging to both file and console"""
        self.logger.setLevel(logging.DEBUG)
        
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
    
    try:
        fixer = MediaFixer()
        # TODO: Implement main conversion logic
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
