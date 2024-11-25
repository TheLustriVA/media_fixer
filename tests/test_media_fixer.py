import os
import pathlib
import pytest
from unittest.mock import Mock, patch, mock_open
from media_fixer import MediaFixer, QueueManager, ConversionConfig, main

@pytest.fixture
def media_fixer():
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda x: f"/usr/bin/{x}"
        fixer = MediaFixer()
        return fixer

@pytest.fixture
def queue_manager(tmp_path):
    return QueueManager(str(tmp_path))

def test_mediafixer_init():
    with patch('shutil.which') as mock_which:
        mock_which.return_value = "/usr/bin/mediainfo"
        fixer = MediaFixer()
        assert fixer.mediainfo_exe == "/usr/bin/mediainfo"
        assert isinstance(fixer.config, ConversionConfig)

def test_mediafixer_init_missing_mediainfo():
    with patch('shutil.which') as mock_which:
        mock_which.return_value = None
        with pytest.raises(RuntimeError, match="Missing 'mediainfo' executable"):
            MediaFixer()

def test_queue_manager_init(tmp_path):
    qm = QueueManager(str(tmp_path), "test_")
    assert qm.prefix == "test_"
    assert isinstance(qm.queues, dict)
    assert len(qm.queues) == 5

def test_queue_manager_initialize_queues(queue_manager):
    queue_manager.initialize_queues()
    for queue_file in queue_manager.queues.values():
        assert queue_file.exists()
        assert queue_file.read_text() == ''

def test_queue_manager_add_to_queue(queue_manager):
    queue_manager.initialize_queues()
    test_entry = "test_video.mp4"
    queue_manager.add_to_queue('failed', test_entry)
    assert queue_manager.get_queue_length('failed') == 1

def test_queue_manager_pop_from_queue(queue_manager):
    queue_manager.initialize_queues()
    test_entry = "test_video.mp4"
    queue_manager.add_to_queue('failed', test_entry)
    popped = queue_manager.pop_from_queue('failed')
    assert popped == test_entry
    assert queue_manager.get_queue_length('failed') == 0

@patch('pymediainfo.MediaInfo.parse')
def test_analyze_video_success(mock_parse, media_fixer):
    mock_general = Mock(track_type="General", format='MP4')
    mock_video = Mock(track_type="Video", format='H264', height=1080)
    mock_parse.return_value = Mock(tracks=[mock_general, mock_video])
    
    result, needs_container, needs_encode, needs_resize = media_fixer.analyze_video("test.mp4")
    assert result == 1
    assert needs_container
    assert needs_encode
    assert needs_resize

@patch('pymediainfo.MediaInfo.parse')
def test_analyze_video_no_changes_needed(mock_parse, media_fixer):
    mock_general = Mock(track_type="General", format='Matroska')
    mock_video = Mock(track_type="Video", format='AV1', height=720)
    mock_parse.return_value = Mock(tracks=[mock_general, mock_video])
    
    result, needs_container, needs_encode, needs_resize = media_fixer.analyze_video("test.mkv")
    assert result == 2
    assert not needs_container
    assert not needs_encode
    assert not needs_resize

@patch('subprocess.run')
@patch('shutil.copy2')
@patch('pathlib.Path')
def test_process_video_success(mock_path, mock_copy, mock_run, media_fixer, tmp_path):
    test_file = tmp_path / "test.mp4"
    test_file.write_text("")
    
    mock_run.return_value.returncode = 0
    mock_path.return_value.exists.return_value = True
    mock_path.return_value.rename.return_value = True
    
    assert media_fixer.process_video(str(test_file), True, True, True)

@patch('subprocess.run')
def test_process_video_failure(mock_run, media_fixer, tmp_path):
    test_file = tmp_path / "test.mp4"
    test_file.write_text("")
    
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Error"
    
    assert not media_fixer.process_video(str(test_file), True, True, True)

def test_setup_logging(media_fixer, tmp_path):
    log_file = tmp_path / "test.log"
    media_fixer.setup_logging(str(log_file), True)
    assert len(media_fixer.logger.handlers) == 2
    assert media_fixer.test_only == True

def test_ffmpeg_variable_interpolation(media_fixer):
    """Test FFmpeg command variable interpolation"""
    mock_path = Mock()
    mock_path.with_name.return_value = pathlib.Path("test.encoded.mkv")
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        media_fixer._encode_video(mock_path, True, True)
        
        cmd_args = mock_run.call_args[0][0]
        # Check variable interpolation
        assert f"-vf scale={media_fixer.config.video_width}:{media_fixer.config.video_height}" in " ".join(cmd_args)
        assert "libsvtav1" in " ".join(cmd_args)

@patch('subprocess.run')
def test_transmux_video_success(mock_run, media_fixer):
    """Test successful video transmuxing"""
    mock_path = Mock()
    mock_path.with_name.return_value = pathlib.Path("test.tmuxed.mkv")
    mock_run.return_value.returncode = 0
    
    assert media_fixer._transmux_video(mock_path)
    assert "-codec copy" in " ".join(mock_run.call_args[0][0])

@patch('subprocess.run')
def test_transmux_video_failure(mock_run, media_fixer):
    """Test failed video transmuxing"""
    mock_path = Mock()
    mock_path.with_name.return_value = pathlib.Path("test.tmuxed.mkv")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Error"
    
    assert not media_fixer._transmux_video(mock_path)

def test_scan_videos(media_fixer, tmp_path):
    """Test video scanning functionality"""
    test_video = tmp_path / "test.mp4"
    test_video.write_text("")
    queue_manager = QueueManager(str(tmp_path))
    
    with patch('subprocess.run') as mock_run:
        # Mock file --mime-type
        mock_run.return_value.stdout = "test.mp4: video/mp4"
        # Mock MediaInfo.parse
        with patch('pymediainfo.MediaInfo.parse') as mock_parse:
            mock_general = Mock(track_type="General", format='MP4')
            mock_video = Mock(track_type="Video", format='H264', height=1080)
            mock_parse.return_value = Mock(tracks=[mock_general, mock_video])
            
            media_fixer.scan_videos(str(tmp_path), queue_manager)
            
            assert queue_manager.get_queue_length('in_progress') == 1

def test_main_function():
    """Test main function execution"""
    test_args = [
        'media_fixer.py',
        '-a',
        '-t',
        '-l', 'test.log'
    ]
    with patch('sys.argv', test_args):
        with patch('media_fixer.MediaFixer') as mock_fixer:
            with patch('media_fixer.QueueManager'):
                main()
                mock_fixer.assert_called_once()

@patch('builtins.input')
def test_interactive_mode(mock_input, media_fixer, tmp_path):
    """Test interactive mode confirmation"""
    mock_input.return_value = ""
    queue_manager = QueueManager(str(tmp_path))
    queue_manager.initialize_queues()
    queue_manager.add_to_queue('in_progress', "test.mp4|||| True True True")
    
    with patch('sys.argv', ['media_fixer.py', '-a', '-i']):
        with patch('media_fixer.MediaFixer.process_video') as mock_process:
            mock_process.return_value = True
            main()
            mock_input.assert_called_once()

def test_invalid_mediainfo_output(media_fixer):
    """Test handling of invalid MediaInfo output"""
    with patch('pymediainfo.MediaInfo.parse') as mock_parse:
        mock_parse.return_value = Mock(tracks=[])
        result, _, _, _ = media_fixer.analyze_video("test.mp4")
        assert result == 0

def test_file_operation_errors(media_fixer):
    """Test handling of file operation errors"""
    with patch('shutil.copy2') as mock_copy:
        mock_copy.side_effect = OSError("Test error")
        assert not media_fixer.process_video("test.mp4", True, True, True)

def test_environment_variable_config():
    """Test configuration from environment variables"""
    with patch.dict('os.environ', {
        'MEDIAFIXER_CONTAINER': 'MP4',
        'MEDIAFIXER_VIDEO_CODEC': 'H264',
        'MEDIAFIXER_VIDEO_WIDTH': '1920',
        'MEDIAFIXER_VIDEO_HEIGHT': '1080'
    }):
        fixer = MediaFixer()
        assert fixer.config.container == 'MP4'
        assert fixer.config.video_codec == 'H264'
        assert fixer.config.video_width == 1920

def test_command_line_arguments():
    """Test various command line argument combinations"""
    test_cases = [
        (['-a'], True),
        (['-p', 'test_path'], True),
        (['-s'], True),
        ([], SystemExit),  # Should exit when no args provided
        (['-f', '-x'], SystemExit)  # Mutually exclusive options
    ]
    
    for args, expected in test_cases:
        with patch('sys.argv', ['media_fixer.py'] + args):
            if isinstance(expected, type) and issubclass(expected, BaseException):
                with pytest.raises(expected):
                    main()
            else:
                main()

def test_queue_manager_edge_cases(queue_manager):
    """Test queue manager edge cases"""
    # Test non-existent queue
    assert queue_manager.get_queue_length('nonexistent') == 0
    
    # Test empty queue pop
    assert queue_manager.pop_from_queue('failed') is None
    
    # Test queue file permissions
    with patch('builtins.open', side_effect=PermissionError):
        assert queue_manager.add_to_queue('failed', 'test.mp4') is None

def test_cleanup_operations(media_fixer, tmp_path):
    """Test cleanup of temporary files"""
    test_temp = tmp_path / "test.mediafixer_working"
    test_temp.write_text("")
    
    queue_manager = QueueManager(str(tmp_path))
    with patch('sys.argv', ['media_fixer.py', '-s']):
        main()
        assert not test_temp.exists()
