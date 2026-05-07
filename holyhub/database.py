## database.py
import sqlite3
from typing import List, Tuple, Any
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)

class Database:
    def __init__(self, db_path: str | None = None):
        # Honor DATABASE_PATH env var so production (Fly volume at /data) and
        # local dev (./holyhub.db) share the same code path.
        self.db_path = db_path or os.environ.get('DATABASE_PATH', 'holyhub.db')
        self.connection = None
        self._initialize_database()

    def _initialize_database(self):
        """Initialize database schema if it doesn't exist."""
        if not os.path.exists(self.db_path):
            self.connect()
            try:
                with open('holyhub/schema.sql', 'r') as f:
                    schema = f.read()
                self.connection.executescript(schema)
                logging.info("Database schema initialized successfully.")
            except Exception as e:
                logging.error(f"Error initializing database: {e}")
                raise
            finally:
                self.close_connection()

    def connect(self):
        """Establishes a connection to the SQLite database."""
        try:
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute('PRAGMA foreign_keys = ON')
            logging.info("Database connection successful.")
        except sqlite3.Error as e:
            logging.error(f"Error connecting to database: {e}")

    def execute_query(self, query: str, params: Tuple = ()) -> List[Tuple[Any, ...]] | None:
        """Executes a given SQL query with optional parameters.

        Args:
            query (str): The SQL query to execute.
            params (Tuple, optional): The parameters to substitute into the query.

        Returns:
            List[Tuple[Any, ...]] | None: The result of the query as a list of tuples for SELECT queries,
            None for other queries, or None on error.
        """
        if self.connection is None:
            logging.error("Database connection not established.")
            return []

        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            if query.strip().upper().startswith("SELECT"):
                result = cursor.fetchall()
                return result
            else:
                self.connection.commit()
                return []
        except sqlite3.Error as e:
            logging.error(f"Error executing query: {e}")
            return []
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def execute_insert(self, query: str, params: tuple = ()) -> int:
        """Executes an INSERT query and returns the new row's id.

        Args:
            query (str): The INSERT SQL query to execute.
            params (tuple, optional): The parameters to substitute into the query.

        Returns:
            int: The lastrowid of the inserted row, or 0 on error.
        """
        if self.connection is None:
            logging.error("Database connection not established.")
            return 0
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            self.connection.commit()
            return cursor.lastrowid
        except Exception as e:
            logging.error(f"Error executing insert: {e}")
            return 0

    def close_connection(self):
        """Closes the database connection."""
        if self.connection:
            self.connection.close()
            logging.info("Database connection closed.")

    def __enter__(self):
        """Enter the runtime context for the database connection."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context and close the connection."""
        self.close_connection()
        if exc_type:
            logging.error(f"Database operation failed: {exc_val}")
