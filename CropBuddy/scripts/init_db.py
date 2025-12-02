import sqlite3

# connect to database (creates if not exists)
conn = sqlite3.connect("database/app.db")
cursor = conn.cursor()



# OTP requests table
cursor.execute("""
CREATE TABLE IF NOT EXISTS otp_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    otp TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()
conn.close()

print("✅ Database ready!")