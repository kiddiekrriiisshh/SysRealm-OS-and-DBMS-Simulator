USE sysrealm;

INSERT INTO users (username, email, password_hash) 
VALUES ('Krish', 'krish@sysrealm.com', 'hashed_password_example');

INSERT INTO resources (resource_id, name, total, icon) VALUES 
('RES_PRINTER', 'PRINTER', 1, 'printer-icon'),
('RES_DISK', 'DISK', 2, 'disk-icon'),
('RES_NETWORK', 'NETWORK', 1, 'network-icon'),
('RES_IO', 'IO_DEVICE', 2, 'io-icon');

INSERT INTO simulation_sessions (session_id, user_id, algorithm, status, quantum, num_processes) 
VALUES ('demo_session_123', 1, 'RoundRobin', 'RUNNING', 2, 4);

INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) VALUES 
('P1', 'demo_session_123', 'Browser', 0, 5, 2, 128, 'READY', 5),
('P2', 'demo_session_123', 'Music Player', 1, 3, 1, 64, 'READY', 3),
('P3', 'demo_session_123', 'Game', 2, 8, 3, 512, 'READY', 8),
('P4', 'demo_session_123', 'Download Manager', 3, 4, 1, 32, 'READY', 4);

INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description) VALUES 
('demo_session_123', 1, 'PROCESS_CREATED', 0, 'Browser process created'),
('demo_session_123', 2, 'PROCESS_CREATED', 1, 'Music Player process created'),
('demo_session_123', 3, 'PROCESS_CREATED', 2, 'Game process created'),
('demo_session_123', 4, 'PROCESS_CREATED', 3, 'Download Manager process created');

INSERT INTO scores (session_id, total_score, reason) 
VALUES ('demo_session_123', 150, 'Initial setup score');
