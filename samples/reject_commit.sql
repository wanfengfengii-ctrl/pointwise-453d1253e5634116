CREATE TEMP TABLE commit_parent (id INTEGER PRIMARY KEY);
CREATE TEMP TABLE commit_child (
    id INTEGER REFERENCES commit_parent(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TEMP TRIGGER reject_report_commit
AFTER INSERT ON main.reports
BEGIN
    INSERT INTO commit_child(id) VALUES (NEW.report_id);
END;
