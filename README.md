# Icecast radio source daemon

```
python3 src/source.py
uvicorn src.cgi:app --port 4444
```

Everything available to use this is in the repository, but one must have `ffmpeg`, `ices`, and `icecast2` installed. IceS can be built from source, get the source tarball here: https://icecast.org/ices/

All python dependencies can be installed with `pip install -r src/requirements.txt`. A virtual env is recommended.
