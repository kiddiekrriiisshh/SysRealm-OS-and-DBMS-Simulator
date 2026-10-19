CREATE DATABASE IF NOT EXISTS sysrealm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sysrealm;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    account_type ENUM('student', 'teacher') NOT NULL DEFAULT 'student',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS simulation_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL UNIQUE,
    user_id INT NULL,
    algorithm VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    quantum INT NULL,
    cpu_utilization DECIMAL(5, 2) DEFAULT 0.00,
    avg_waiting_time DECIMAL(10, 2) DEFAULT 0.00,
    avg_turnaround_time DECIMAL(10, 2) DEFAULT 0.00,
    num_processes INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS processes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pid VARCHAR(50) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    arrival_time INT NOT NULL,
    burst_time INT NOT NULL,
    priority INT NOT NULL,
    memory_mb INT NOT NULL,
    state ENUM('NEW','READY','RUNNING','WAITING','TERMINATED') NOT NULL DEFAULT 'NEW',
    remaining_time INT NOT NULL DEFAULT 0,
    start_time INT NULL,
    completion_time INT NULL,
    waiting_time INT DEFAULT 0,
    turnaround_time INT DEFAULT 0,
    response_time INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
    UNIQUE KEY unique_session_pid (session_id, pid),
    INDEX idx_session_id (session_id),
    INDEX idx_pid (pid)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS resources (
    id INT AUTO_INCREMENT PRIMARY KEY,
    resource_id VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    total INT NOT NULL,
    icon VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS resource_allocations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    resource_id VARCHAR(50) NOT NULL,
    pid VARCHAR(50) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    count INT DEFAULT 1,
    status ENUM('ALLOCATED','WAITING','RELEASED') NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (resource_id) REFERENCES resources(resource_id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (session_id, pid) REFERENCES processes(session_id, pid) ON DELETE CASCADE,
    INDEX idx_session_pid (session_id, pid)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS process_activity_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    process_id VARCHAR(50) NULL,
    event_type VARCHAR(50) NOT NULL,
    simulation_time INT DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
    INDEX idx_log_session (session_id),
    INDEX idx_log_pid (process_id)
) ENGINE=InnoDB;

-- Process State Transition History Table (Tracks Operating Systems Lifecycle Transitions)
CREATE TABLE IF NOT EXISTS process_state_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    pid VARCHAR(50) NOT NULL,
    old_state VARCHAR(20) NOT NULL,
    new_state VARCHAR(20) NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
    INDEX idx_history_session_pid (session_id, pid),
    INDEX idx_history_changed (changed_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    size_kb INT NOT NULL,
    owner_pid VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS scores (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL UNIQUE,
    total_score INT DEFAULT 0,
    reason VARCHAR(255),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================================
-- MYSQL TRIGGERS FOR SYSREALM OS & DBMS ENGINE
-- ============================================================================

DROP TRIGGER IF EXISTS trg_before_process_insert;
DROP TRIGGER IF EXISTS trg_before_process_update;
DROP TRIGGER IF EXISTS trg_after_process_insert;
DROP TRIGGER IF EXISTS trg_after_process_state_update;
DROP TRIGGER IF EXISTS trg_after_process_terminated;
DROP TRIGGER IF EXISTS trg_after_process_delete;
DROP TRIGGER IF EXISTS trg_after_resource_allocation;

DELIMITER $$

-- 1. BEFORE INSERT Trigger: Enforce OS hardware & scheduling bounds at DBMS level
CREATE TRIGGER trg_before_process_insert
BEFORE INSERT ON processes
FOR EACH ROW
BEGIN
    IF NEW.burst_time <= 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_insert]: Burst time must be greater than 0';
    END IF;
    IF NEW.memory_mb <= 0 OR NEW.memory_mb > 16384 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_insert]: Memory allocation must be between 1 MB and 16384 MB (16 GB)';
    END IF;
    IF NEW.arrival_time < 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_insert]: Arrival time cannot be negative';
    END IF;
    IF NEW.state NOT IN ('NEW', 'READY', 'RUNNING', 'WAITING', 'TERMINATED') THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_insert]: Invalid process state';
    END IF;
END$$

-- 2. BEFORE UPDATE Trigger: Enforce constraints on process modifications
CREATE TRIGGER trg_before_process_update
BEFORE UPDATE ON processes
FOR EACH ROW
BEGIN
    IF NEW.burst_time <= 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_update]: Burst time must be greater than 0';
    END IF;
    IF NEW.memory_mb <= 0 OR NEW.memory_mb > 16384 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_update]: Memory allocation must be between 1 MB and 16384 MB (16 GB)';
    END IF;
    IF NEW.arrival_time < 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_update]: Arrival time cannot be negative';
    END IF;
    IF NEW.state NOT IN ('NEW', 'READY', 'RUNNING', 'WAITING', 'TERMINATED') THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_update]: Invalid process state';
    END IF;
END$$

-- 3. AFTER INSERT Trigger: Auto-increment session process counter & insert creation audit log
CREATE TRIGGER trg_after_process_insert
AFTER INSERT ON processes
FOR EACH ROW
BEGIN
    UPDATE simulation_sessions
    SET num_processes = num_processes + 1
    WHERE session_id = NEW.session_id;

    INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
    VALUES (
        NEW.session_id,
        NEW.pid,
        'PROCESS_CREATED',
        NEW.arrival_time,
        CONCAT('[Trigger: trg_after_process_insert] Process ', NEW.name, ' (', NEW.pid, ') created with burst=', NEW.burst_time, 'ms, mem=', NEW.memory_mb, 'MB')
    );

    IF NEW.state = 'TERMINATED' THEN
        INSERT INTO scores (session_id, total_score, reason)
        VALUES (NEW.session_id, 10, CONCAT('Auto-awarded by trigger for completing ', NEW.pid))
        ON DUPLICATE KEY UPDATE
            total_score = total_score + 10,
            reason = CONCAT('Auto-awarded +10 by trigger for completing ', NEW.pid);
    END IF;
END$$

-- 4. AFTER UPDATE Trigger: Record process state transitions in process_state_history
CREATE TRIGGER trg_after_process_state_update
AFTER UPDATE ON processes
FOR EACH ROW
BEGIN
    IF OLD.state <> NEW.state THEN
        INSERT INTO process_state_history (session_id, pid, old_state, new_state, changed_at)
        VALUES (NEW.session_id, NEW.pid, OLD.state, NEW.state, NOW());
    END IF;
END$$

-- 5. AFTER UPDATE Trigger: Auto-award +10 score & log completion when process state -> TERMINATED
CREATE TRIGGER trg_after_process_terminated
AFTER UPDATE ON processes
FOR EACH ROW
BEGIN
    IF NEW.state = 'TERMINATED' AND OLD.state <> 'TERMINATED' THEN
        INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
        VALUES (
            NEW.session_id,
            NEW.pid,
            'PROCESS_TERMINATED',
            COALESCE(NEW.completion_time, 0),
            CONCAT('[Trigger: trg_after_process_terminated] Process ', NEW.name, ' (', NEW.pid, ') completed execution. TAT=', NEW.turnaround_time, ', WT=', NEW.waiting_time)
        );

        INSERT INTO scores (session_id, total_score, reason)
        VALUES (NEW.session_id, 10, CONCAT('Auto-awarded by trigger for completing ', NEW.pid))
        ON DUPLICATE KEY UPDATE
            total_score = total_score + 10,
            reason = CONCAT('Auto-awarded +10 by trigger for completing ', NEW.pid);
    END IF;
END$$

-- 6. AFTER DELETE Trigger: Decrement session process counter & log removal
CREATE TRIGGER trg_after_process_delete
AFTER DELETE ON processes
FOR EACH ROW
BEGIN
    UPDATE simulation_sessions
    SET num_processes = GREATEST(0, num_processes - 1)
    WHERE session_id = OLD.session_id;

    INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
    VALUES (
        OLD.session_id,
        OLD.pid,
        'PROCESS_DELETED',
        0,
        CONCAT('[Trigger: trg_after_process_delete] Process ', OLD.name, ' (', OLD.pid, ') removed from session')
    );
END$$

-- 7. AFTER INSERT Trigger: Auto-audit hardware resource requests & allocations
CREATE TRIGGER trg_after_resource_allocation
AFTER INSERT ON resource_allocations
FOR EACH ROW
BEGIN
    INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
    VALUES (
        NEW.session_id,
        NEW.pid,
        CONCAT('RESOURCE_', UPPER(NEW.status)),
        0,
        CONCAT('[Trigger: trg_after_resource_allocation] Process ', NEW.pid, ' ', NEW.status, ' resource ', NEW.resource_id, ' (count=', NEW.count, ')')
    );
END$$

DELIMITER ;

-- 9. Lab Assignments Table (Teacher-to-Student Live Challenges)
CREATE TABLE IF NOT EXISTS lab_assignments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(150) NOT NULL,
    description TEXT,
    target_panel VARCHAR(40) NOT NULL DEFAULT 'scheduler',
    required_algo VARCHAR(40) NOT NULL DEFAULT 'RoundRobin',
    max_awt DECIMAL(6, 2) NULL,
    points INT NOT NULL DEFAULT 50,
    given_query TEXT NULL,
    expected_rules TEXT NULL,
    workload_json TEXT NULL,
    allowed_algorithms_json TEXT NULL,
    optimization_objective VARCHAR(50) NULL,
    round_robin_quantum INT DEFAULT 2,
    created_by VARCHAR(100) DEFAULT 'Instructor',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 10. Assignment Submissions Table (Tracks student completions via Foreign Key JOIN)
CREATE TABLE IF NOT EXISTS assignment_submissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    assignment_id INT NOT NULL,
    student_email VARCHAR(100) NOT NULL,
    student_name VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'COMPLETED',
    score_awarded INT NOT NULL DEFAULT 50,
    verification_note VARCHAR(255) NULL,
    submitted_query TEXT NULL,
    student_explanation TEXT NULL,
    cbo_metrics TEXT NULL,
    selected_algo VARCHAR(50) NULL,
    submitted_quantum INT NULL,
    objective_value DECIMAL(10, 2) NULL,
    scheduling_metrics TEXT NULL,
    gantt_json TEXT NULL,
    attempts_count INT DEFAULT 1,
    completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_assignment_student (assignment_id, student_email),
    FOREIGN KEY (assignment_id) REFERENCES lab_assignments(id) ON DELETE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 10b. Student XP Awards Table (Atomic duplicate-proof ledger for assignment rewards)
CREATE TABLE IF NOT EXISTS student_xp_awards (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_email VARCHAR(100) NOT NULL,
    student_name VARCHAR(100),
    assignment_id INT NOT NULL,
    points_awarded INT NOT NULL,
    award_reason VARCHAR(255),
    awarded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_award_student_assignment (assignment_id, student_email),
    FOREIGN KEY (assignment_id) REFERENCES lab_assignments(id) ON DELETE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 11. Simulation Runs Table (Persistent Simulation History & Experiment Archive)
CREATE TABLE IF NOT EXISTS simulation_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL UNIQUE,
    session_id VARCHAR(255) NULL,
    user_id INT NULL,
    run_name VARCHAR(150) NOT NULL,
    algorithm VARCHAR(50) NOT NULL,
    quantum INT NULL,
    process_count INT NOT NULL DEFAULT 0,
    workload_hash VARCHAR(64) NOT NULL,
    avg_waiting_time DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    avg_turnaround_time DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    avg_response_time DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    cpu_utilization DECIMAL(5, 2) NOT NULL DEFAULT 0.00,
    throughput DECIMAL(8, 4) NOT NULL DEFAULT 0.0000,
    context_switches INT NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED',
    gantt_json LONGTEXT NULL,
    metrics_json TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_simrun_workload (workload_hash),
    INDEX idx_simrun_algo (algorithm),
    INDEX idx_simrun_created (created_at),
    INDEX idx_simrun_session (session_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 12. Simulation Run Processes Table (Process-Level Execution Results for Reproducibility)
CREATE TABLE IF NOT EXISTS simulation_run_processes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    pid VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    arrival_time INT NOT NULL,
    burst_time INT NOT NULL,
    priority INT NOT NULL DEFAULT 1,
    memory_mb INT NOT NULL DEFAULT 512,
    start_time INT NULL,
    completion_time INT NULL,
    waiting_time INT NOT NULL DEFAULT 0,
    turnaround_time INT NOT NULL DEFAULT 0,
    response_time INT NULL,
    execution_order INT NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
    UNIQUE KEY uk_simrun_proc (run_id, pid),
    INDEX idx_simrunproc_run (run_id),
    INDEX idx_simrunproc_pid (pid)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
