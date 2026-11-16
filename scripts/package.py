"""Package source and prebuilt UI; exclude credentials, dependencies and all runtime media."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib

root=Path(__file__).resolve().parents[1]
release=root/'release'
release.mkdir(exist_ok=True)
archive=release/'VI-ClipForge-1.0.zip'
excluded={'.git','.venv','node_modules','storage','release','__pycache__','.pytest_cache','.ruff_cache','.env','.DS_Store'}
with ZipFile(archive,'w',ZIP_DEFLATED) as bundle:
    for path in sorted(root.rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(root)
        if any(part in excluded or part.endswith('.egg-info') for part in relative.parts):continue
        if path.suffix in {'.db','.pyc','.mp4','.mov','.m4v','.webm','.mkv'} or '.db-' in path.name:continue
        bundle.write(path,Path('VI-ClipForge')/relative)
with ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    assert any(name.endswith('frontend/dist/index.html') for name in bundle.namelist())
    assert not any('/.env' in name and not name.endswith('/.env.example') for name in bundle.namelist())
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
(release/'SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n')
print(f'{archive}\n{archive.stat().st_size:,} bytes\nSHA-256 {digest}')
