# Icecast radio source daemon

```
python3 src/source.py
uvicorn src.cgi:app --port 4444
```

Everything available to use this is in the repository, but one must have `ffmpeg`, `ices`, and `icecast2` installed. IceS can be built from source, get the source tarball here: https://icecast.org/ices/

All python dependencies can be installed with `pip install -r requirements.txt`. A virtual env is recommended.

Documentation for the `user_config.xml` file:

The `<?xml version="1.0" encoding="UTF-8"?>` is called the "xml preamble". It just specifies information used in parsing xml files.

The xml root element is `<config>`. The child elements of the root must be `<timeslot>` elements. It can have any number (0 or more) of `<timeslot>` children, each defining a separate time slot for the stream.

A `<timeslot>` element must have 4 children (otherwise parsing will fail):
- `<genre>` element. It encloses a string which describes the time slot's genre of music.
- `<time>` element. It must contain one `<start>` and one `<end>` child elements. These both must enclose a string representing a time in HH:MM format (24 hour time). These strings represent the start and end of the time slot, respectively.
- `<albums>` element. It encloses a string representing the path to the directory which will be searched to find albums. An album is just a folder inside this directory, which contains music files and a cover image.
- `<blacklist>` element. It can contain 0 or more children `<album>` elements, each enclosing a string representing the name of an album folder. Every folder named in this blacklist will be skipped when loading albums.
