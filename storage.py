import sqlite3
from datetime import datetime, timedelta
from os.path import dirname, join
from secrets import token_hex

from crypt import gen_salt, hash_password


class CursorManager:
    """Class to manage acquiring a cursor and committing afterward."""

    @staticmethod
    def _connection():
        return sqlite3.connect(join(dirname(__file__), "resistance.sqlite3"))

    def __enter__(self):
        """Obtain a connection and cursor."""
        self._conn = self._connection()
        return self._conn.cursor()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Commit the connection."""
        self._conn.commit()
        return False


class Storage:
    TABLE_NAME = None
    TABLE_SCHEMA = ""

    @property
    def cursor(self):
        return CursorManager()

    def __init__(self):
        if self.TABLE_NAME is None:
            raise NotImplementedError("`TABLE_NAME` needs to be specified.")
        with self.cursor as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS {} ({})".format(
                    self.TABLE_NAME, self.TABLE_SCHEMA
                )
            )

    def __len__(self):
        with self.cursor as cursor:
            return cursor.execute(
                "SELECT Count(*) FROM {}".format(self.TABLE_NAME)
            ).fetchone()[0]

    def _contains(self, column_name, item):
        with self.cursor as cursor:
            return cursor.execute(
                "SELECT {col} FROM {tab} WHERE {col}=?".format(
                    tab=self.TABLE_NAME, col=column_name
                ),
                (item,),
            ).fetchone()

    def _get_row(self, key_name, value, *columns):
        with self.cursor as cursor:
            return cursor.execute(
                "SELECT {cols} FROM {tab} WHERE {key}=?".format(
                    tab=self.TABLE_NAME, key=key_name, cols=", ".join(columns)
                ),
                (value,),
            ).fetchone()

    def _iterate_column(self, column_name):
        with self.cursor as cursor:
            return (
                row[0]
                for row in cursor.execute(
                    "SELECT {col} from {tab} ORDER BY {col} ASC".format(
                        col=column_name, tab=self.TABLE_NAME
                    )
                )
            )

    def _iterate_columns(self, *columns, order_by=""):
        with self.cursor as cursor:
            return cursor.execute(
                "SELECT {cols} from {tab} {order}".format(
                    cols=", ".join(columns), tab=self.TABLE_NAME, order=order_by
                )
            )

    def _remove(self, column_name, value):
        with self.cursor as cursor:
            cursor.execute(
                "DELETE FROM {tab} WHERE {col}=?".format(
                    tab=self.TABLE_NAME, col=column_name
                ),
                (value,),
            )

    def clear(self):
        with self.cursor as cursor:
            cursor.execute("DROP TABLE {}".format(self.TABLE_NAME))
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS {} ({})".format(
                    self.TABLE_NAME, self.TABLE_SCHEMA
                )
            )


class Cookies(Storage):
    TABLE_NAME = "cookies"
    TABLE_SCHEMA = "cookie TEXT PRIMARY KEY, user TEXT, expiration DATETIME NOT NULL"
    VALID_LENGTH = timedelta(days=7)

    def check(self, cookie):
        """Check if a cookie is valid."""
        with self.cursor as cursor:
            return (
                cursor.execute(
                    "SELECT * FROM {} WHERE cookie=? AND expiration>?".format(
                        self.TABLE_NAME
                    ),
                    (cookie, int(datetime.now().timestamp())),
                ).fetchone()
                is not None
            )

    def new(self, user):
        """Store a new cookie and return it."""
        val = token_hex(30)
        exp_date = int((datetime.now() + self.VALID_LENGTH).timestamp())
        with self.cursor as cursor:
            cursor.execute(
                "INSERT INTO {} VALUES (?, ?, ?)".format(self.TABLE_NAME),
                (val, user, exp_date),
            )
        return val

    def prune(self):
        """Remove cookies that are out-of-date."""
        now = int(datetime.now().timestamp())
        with self.cursor as cursor:
            cursor.execute(
                "DELETE FROM {} WHERE expiration < ?".format(self.TABLE_NAME), (now,)
            )

    def remove(self, cookie):
        """Remove a cookie as part of a logout."""
        self._remove("cookie", cookie)

    def user(self, cookie):
        """Get the username associated with the auth cookie."""
        if cookie is None:
            return None
        return self._get_row("cookie", cookie, "user")[0]


class Users(Storage):
    TABLE_NAME = "users"
    TABLE_SCHEMA = "username_lower TEXT PRIMARY KEY, username TEXT, passwd_hash TEXT NOT NULL, salt TEXT NOT NULL"

    def register(self, username, password):
        """Check if a user can be registered, and if so, register them."""
        with self.cursor as cursor:
            if (
                cursor.execute(
                    "SELECT * FROM {} WHERE username_lower=?".format(self.TABLE_NAME),
                    (username.lower(),),
                ).fetchone()
                is not None
            ):
                return "That username is taken."
            salt = gen_salt()
            passwd_hash = hash_password(password, salt)
            cursor.execute(
                "INSERT INTO {} VALUES (?, ?, ?, ?)".format(self.TABLE_NAME),
                (username.lower(), username, passwd_hash, salt),
            )

    def authenticate(self, username, password):
        """Check a user's credentials, returning their true username if valid."""
        with self.cursor as cursor:
            user_row = cursor.execute(
                "SELECT username, passwd_hash, salt FROM {} WHERE username_lower=?".format(
                    self.TABLE_NAME
                ),
                (username.lower(),),
            ).fetchone()
            if user_row is None:
                return
            true_username, passwd_hash, salt = user_row
            if passwd_hash == hash_password(password, salt):
                return true_username
