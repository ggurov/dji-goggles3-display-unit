#!/usr/bin/env python3
"""Add novice_guidance=1 to a copy of us.db and print resulting rows."""
import sqlite3, sys

p = sys.argv[1]
con = sqlite3.connect(p)
cur = con.cursor()
cur.execute(
    "INSERT OR REPLACE INTO user_settings_kv(name,value) VALUES('novice_guidance','1')")
con.commit()
print("rows after edit:")
for r in cur.execute("SELECT name,value FROM user_settings_kv ORDER BY name"):
    print("  ", r[0], "=", r[1])
con.close()
