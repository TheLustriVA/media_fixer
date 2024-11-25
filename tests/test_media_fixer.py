import os
import pathlib
import pytest
from unittest.mock import Mock, patch, mock_open
from media_fixer import MediaFixer, QueueManager, ConversionConfig

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
