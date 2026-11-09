"""Windows CurrentUser DPAPI. Plaintext never goes through a file or command line.

The encrypted backup can be read only by the same Windows account on this PC.
This is a lab restart mechanism, not a portable/team disaster recovery vault.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]


def transform(value, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Protected recovery requires Windows CurrentUser DPAPI')
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise RuntimeError('Cannot decrypt recovery file for this Windows user' if decrypt else 'Cannot protect recovery file')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(transform(json.dumps(value).encode('utf-8')))
    temporary.replace(path)
    if load(path) != value:
        raise ValueError('Protected backup round-trip did not match')


def load(path):
    return json.loads(transform(Path(path).read_bytes(), decrypt=True).decode('utf-8'))
