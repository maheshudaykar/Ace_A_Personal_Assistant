"""File operations tool for ACE - Phase 0 dummy tool"""

from pathlib import Path
import logging

logger = logging.getLogger("ACE.FileOperations")


def read_file(file_path: str, encoding: str = "utf-8") -> str:
    """
    Read file contents safely.
    
    Args:
        file_path: Path to file
        encoding: File encoding (default: utf-8)
    
    Returns:
        File contents as string
    """
    try:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        logger.info(f"Reading file: {file_path}")
        with open(path, "r", encoding=encoding) as f:
            content = f.read()
        
        logger.info(f"Successfully read {len(content)} characters from {file_path}")
        return content
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        raise


def list_files(directory: str) -> list[str]:
    """
    List files in directory.
    
    Args:
        directory: Directory path
    
    Returns:
        List of file paths
    """
    try:
        path = Path(directory)
        if not path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        logger.info(f"Listing files in: {directory}")
        files = [str(f) for f in path.iterdir()]
        logger.info(f"Found {len(files)} items in {directory}")
        return files
    except Exception as e:
        logger.error(f"Error listing files in {directory}: {e}")
        raise


def write_file(file_path: str, content: str, encoding: str = "utf-8") -> bool:
    """
    Write content to file.
    
    Args:
        file_path: Path to file
        content: Content to write
        encoding: File encoding (default: utf-8)
    
    Returns:
        True if successful
    """
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Writing file: {file_path}")
        with open(path, "w", encoding=encoding) as f:
            f.write(content)
        
        logger.info(f"Successfully wrote {len(content)} characters to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error writing file {file_path}: {e}")
        raise
