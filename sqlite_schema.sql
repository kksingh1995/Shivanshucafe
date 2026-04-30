PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS centers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  center_code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  address TEXT,
  city TEXT,
  contact TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  public_id TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('admin', 'audiologist', 'operator')),
  name TEXT NOT NULL,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  mobile TEXT,
  license_no TEXT,
  center_id INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (center_id) REFERENCES centers(id)
);

CREATE TABLE IF NOT EXISTS children (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  child_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  age INTEGER NOT NULL,
  father_name TEXT NOT NULL,
  mobile TEXT NOT NULL,
  gender TEXT,
  dob TEXT,
  mother_name TEXT,
  address TEXT,
  referred_by TEXT,
  enrolled_by INTEGER NOT NULL,
  center_id INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (enrolled_by) REFERENCES users(id),
  FOREIGN KEY (center_id) REFERENCES centers(id)
);

CREATE TABLE IF NOT EXISTS tests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  test_id TEXT NOT NULL UNIQUE,
  child_ref INTEGER NOT NULL,
  operator_ref INTEGER NOT NULL,
  right_ear_json TEXT NOT NULL,
  left_ear_json TEXT NOT NULL,
  pta_right REAL,
  pta_left REAL,
  classification_right TEXT,
  classification_left TEXT,
  duration_sec INTEGER,
  summary_text TEXT,
  recommendation_text TEXT,
  hearing_aid_guidance TEXT,
  audiogram_svg TEXT,
  status TEXT NOT NULL DEFAULT 'submitted',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (child_ref) REFERENCES children(id),
  FOREIGN KEY (operator_ref) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS thresholds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  test_ref INTEGER NOT NULL,
  ear TEXT NOT NULL CHECK (ear IN ('right', 'left')),
  frequency_hz INTEGER NOT NULL,
  threshold_dbhl TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (test_ref, ear, frequency_hz),
  FOREIGN KEY (test_ref) REFERENCES tests(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id TEXT NOT NULL UNIQUE,
  test_ref INTEGER NOT NULL UNIQUE,
  audiologist_ref INTEGER NOT NULL,
  classification_right TEXT,
  classification_left TEXT,
  remarks TEXT,
  recommendation TEXT,
  summary_text TEXT,
  hearing_aid_guidance TEXT,
  audiogram_svg TEXT,
  status TEXT NOT NULL DEFAULT 'verified',
  verified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (test_ref) REFERENCES tests(id),
  FOREIGN KEY (audiologist_ref) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  org TEXT NOT NULL,
  cat TEXT NOT NULL DEFAULT 'govt',
  edu TEXT NOT NULL DEFAULT 'N/A',
  loc TEXT NOT NULL DEFAULT 'N/A',
  sal TEXT NOT NULL DEFAULT 'N/A',
  status TEXT NOT NULL DEFAULT 'published',
  post_date TEXT,
  apply_date TEXT,
  deadline TEXT NOT NULL DEFAULT 'Open',
  link TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS news_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'new',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS site_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL CHECK (role IN ('admin', 'student')),
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  mobile TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  course TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS site_saved_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  job_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(student_id, job_id),
  FOREIGN KEY (student_id) REFERENCES site_users(id) ON DELETE CASCADE,
  FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO centers (id, center_code, name, address, city, contact)
VALUES (1, 'CTR-0001', 'AudiCare Patna Center', 'Boring Road', 'Patna', '0612-123456');

INSERT OR IGNORE INTO users (id, public_id, role, name, username, password_hash, mobile, center_id)
VALUES
  (1, 'USR-ADMIN-001', 'admin', 'Administrator', 'admin', 'admin123', '9999999999', 1),
  (2, 'USR-AUD-001', 'audiologist', 'Dr. Ramesh Kumar', 'audiologist1', 'audio123', '9876543210', 1);

INSERT OR IGNORE INTO jobs (id, title, org, cat, edu, loc, sal, deadline, link)
VALUES
  (1, 'Railway Group D Recruitment 2026 (10,000+ Posts)', 'RRB / Indian Railways', 'railway', '10th Pass', 'All India', 'Rs 18,000-Rs 56,900', '30 April 2026', 'https://indianrailways.gov.in'),
  (2, 'Bihar Police Constable Bharti 2026 (21,391 Posts)', 'Bihar Police', 'defence', '12th Pass', 'Bihar', 'Rs 21,700+', '10 May 2026', 'https://csbc.bihar.gov.in'),
  (3, 'Bihar SSC Inter Level Recruitment 2026', 'Bihar Staff Selection Commission', 'govt', '12th Pass', 'Bihar', 'Rs 20,000-Rs 60,000', '15 May 2026', 'https://bssc.bihar.gov.in'),
  (4, 'IBPS PO Recruitment 2026', 'Institute of Banking Personnel', 'bank', 'Graduate', 'All India', 'Rs 36,000-Rs 63,840', '20 May 2026', 'https://ibps.in'),
  (5, 'Indian Army Agniveer Recruitment 2026', 'Indian Army', 'defence', '10th/12th Pass', 'All India', 'Rs 30,000-Rs 40,000', '25 April 2026', 'https://joinindianarmy.nic.in'),
  (6, 'SBI Clerk (Junior Associate) Bharti 2026', 'State Bank of India', 'bank', 'Graduate', 'All India', 'Rs 26,000-Rs 35,000', '12 May 2026', 'https://sbi.co.in'),
  (7, 'SSC CHSL (10+2 Level) Exam 2026', 'Staff Selection Commission', 'govt', '12th Pass', 'All India', 'Rs 25,500-Rs 81,100', '3 May 2026', 'https://ssc.nic.in'),
  (8, 'Data Entry Operator - Work From Home', 'Various Companies', 'private', '10th/12th Pass', 'Bihar / Remote', 'Rs 12,000-Rs 25,000', 'Open', ''),
  (9, 'BSEB Inter Admission 2026-28 Online', 'Bihar School Examination Board', 'govt', '10th Pass', 'Bihar', 'N/A', '18 April 2026', 'http://ofssbihar.org');

INSERT OR IGNORE INTO news_items (id, text, type)
VALUES
  (1, 'BSEB INTER ADMISSION SESSION 2026-28 ONLINE - Last Date: 18 April', 'urgent'),
  (2, 'Bihar PE PM PMM Entrance Form Online 2026 - Last Date: 21.04.2026', 'new'),
  (3, 'Bihar ITI CAT Entrance Form Online 2026 - Last Date: 14.04.2026', 'new'),
  (4, 'Agniveer Army Form Online 2026 - Last Date: 10-04-2026', 'urgent'),
  (5, 'CBSE 10th Board Result 2026 - Check Karein Abhi', 'info'),
  (6, 'BPSC AEDO Admit Card 2026 Released', 'new'),
  (7, 'DELE.d Application Form 2026 - Last Date: 09 January 2026', 'info'),
  (8, 'UP Police Constable Bharti 2026 - Online Form Open', 'new');
