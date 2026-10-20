import path from "node:path";
import Database from "better-sqlite3";

// Same default the Python pipeline resolves to (statify/config.py), so both
// processes agree on one file without either needing to be told where it is.
const DB_PATH = path.join(process.cwd(), "data", "statify.db");

let db: Database.Database | null = null;

// A singleton, read-only connection. The dashboard only ever reads; writes
// are the Python pipeline's job, run manually and never from this app.
export function getDb(): Database.Database {
  if (!db) {
    db = new Database(DB_PATH, { readonly: true, fileMustExist: true });
  }
  return db;
}
