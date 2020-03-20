from hashlib import pbkdf2_hmac
from secrets import token_urlsafe


def gen_salt():
    return token_urlsafe(32)


def hash_password(password, salt):
    return pbkdf2_hmac(
        "sha512", bytes(password, "utf-8"), bytes(salt, "ascii"), 100000
    ).hex()
