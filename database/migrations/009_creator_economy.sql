PRAGMA foreign_keys = ON;

CREATE TABLE creator_profiles (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    publisher_id TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    bio TEXT NOT NULL DEFAULT '',
    avatar_reference TEXT,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','VERIFIED','BLOCKED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY(publisher_id) REFERENCES publishers(id) ON DELETE RESTRICT
);

CREATE TABLE package_versions (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    creator_id TEXT NOT NULL,
    version TEXT NOT NULL,
    manifest TEXT NOT NULL,
    checksum TEXT NOT NULL,
    changelog TEXT NOT NULL DEFAULT '',
    compatibility TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('DRAFT','SUBMITTED','VALIDATING','APPROVED','PUBLISHED','ARCHIVED','ROLLED_BACK','FAILED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    FOREIGN KEY(creator_id) REFERENCES creator_profiles(id) ON DELETE RESTRICT,
    UNIQUE(package_id,version)
);

CREATE TABLE creator_verification (
    creator_id TEXT PRIMARY KEY,
    level TEXT NOT NULL CHECK (level IN ('NEW_CREATOR','VERIFIED_CREATOR','TRUSTED_CREATOR')),
    status TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','REVOKED')),
    verified_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(creator_id) REFERENCES creator_profiles(id) ON DELETE RESTRICT
);

CREATE TABLE creator_metrics (
    id TEXT PRIMARY KEY,
    creator_id TEXT NOT NULL,
    package_id TEXT,
    metric TEXT NOT NULL CHECK (metric IN ('EXECUTION','SUCCESS','ERROR')),
    value INTEGER NOT NULL CHECK (value >= 0),
    result TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(creator_id) REFERENCES creator_profiles(id) ON DELETE RESTRICT,
    FOREIGN KEY(package_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT
);

CREATE TABLE quality_scores (
    package_id TEXT NOT NULL,
    version TEXT NOT NULL,
    security_score INTEGER NOT NULL CHECK (security_score BETWEEN 0 AND 100),
    compatibility_score INTEGER NOT NULL CHECK (compatibility_score BETWEEN 0 AND 100),
    reliability_score INTEGER NOT NULL CHECK (reliability_score BETWEEN 0 AND 100),
    user_rating REAL NOT NULL CHECK (user_rating BETWEEN 0 AND 5),
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    grade TEXT NOT NULL CHECK (grade IN ('A+','A','B','C','D','F')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(package_id,version),
    FOREIGN KEY(package_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT
);

CREATE TABLE review_votes (
    review_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    vote INTEGER NOT NULL CHECK (vote IN (-1,1)),
    created_at TEXT NOT NULL,
    PRIMARY KEY(review_id,user_id),
    FOREIGN KEY(review_id) REFERENCES reviews(id) ON DELETE RESTRICT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TRIGGER package_versions_protect_published BEFORE UPDATE ON package_versions
WHEN OLD.status IN ('PUBLISHED','ARCHIVED','ROLLED_BACK') AND (
    NEW.package_id != OLD.package_id OR NEW.creator_id != OLD.creator_id OR
    NEW.version != OLD.version OR NEW.manifest != OLD.manifest OR NEW.checksum != OLD.checksum
) BEGIN SELECT RAISE(ABORT,'published creator package content is immutable'); END;
CREATE TRIGGER package_versions_no_delete BEFORE DELETE ON package_versions BEGIN SELECT RAISE(ABORT,'creator package versions are immutable'); END;
CREATE TRIGGER creator_metrics_no_update BEFORE UPDATE ON creator_metrics BEGIN SELECT RAISE(ABORT,'creator metrics are immutable'); END;
CREATE TRIGGER creator_metrics_no_delete BEFORE DELETE ON creator_metrics BEGIN SELECT RAISE(ABORT,'creator metrics are immutable'); END;

CREATE INDEX idx_creator_profiles_status ON creator_profiles(status,display_name);
CREATE INDEX idx_package_versions_creator ON package_versions(creator_id,status,updated_at);
CREATE INDEX idx_package_versions_package ON package_versions(package_id,created_at);
CREATE INDEX idx_creator_metrics_package ON creator_metrics(creator_id,package_id,created_at);
CREATE INDEX idx_review_votes_review ON review_votes(review_id,vote);
