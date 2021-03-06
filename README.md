# tftp.py
Python implementation of [RFC-1350](https://tools.ietf.org/html/rfc1350): TFTP

This project is intended for educational purposes only and holds no warranty of any kind for fitness or accuracy.

## Usage

tftp.py defaults to port 20069 instead of 69 so privileged access is not requred.

To run:

```
cd /path/to/repo/tftp.py
python3 tftp
```

To test, use a standard TFTP client:

```
tftp 127.0.0.1 20069
tftp> binary
tftp> verbose
tftp> trace
tftp> put <some_localfile> <some_remotefile>
tftp> get <some_remotefile>
```
## Unit Tests
To run unit tests (which set logging to debug):

```
cd /path/to/repo/tftp.py
python3 -m unittest discover ./tftp
```

## ToDo:
- Allow command-line setting of logging level and listening port
