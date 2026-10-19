"""
Unit and Integration Tests for SysRealm Teacher-Published Virtual Apps Scheduling Assignments
Validates:
1. Workload validation (1-20 processes, unique PIDs, non-negative arrival, positive burst, priority 1-10)
2. Isolated simulation execution without mutating global engine.process_manager or engine.score
3. Objective evaluation across allowed algorithms (AWT, TAT, RT) and mathematical tie handling (tolerance <= 0.05)
4. Teacher assignment publication with custom workload, allowed algorithms, and objective specification
5. Teacher assignment publication input validation and error handling
6. Prevention of completion bypass via generic /api/assignments/<id>/complete (HTTP 400 rejection)
7. Student retrieval of assignment details via /api/assignments/<id>/virtual-apps
8. Student isolated algorithm execution via /api/assignments/<id>/virtual-apps/run and rejection of unpermitted algorithms
9. Student submission of optimal algorithm: atomic XP award and persistence in student_xp_awards and assignment_submissions
10. Retry idempotency: prevention of duplicate XP awards on subsequent successful submissions
11. Student submission of suboptimal algorithm: informative diagnostic feedback, no XP awarded, incremented attempts count
12. Teacher gradebook JOIN inspection reflecting student algorithm choice, objective value, and verification status
"""

import unittest
import json
import sqlite3
from app import app, engine, _get_sqlite_mirror
from backend import isolated_scheduler


class TestVirtualAppsAssignments(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        
        # Ensure database tables exist
        conn = _get_sqlite_mirror()
        cur = conn.cursor()
        cur.execute("DELETE FROM student_xp_awards WHERE student_email = 'test_student@sysrealm.com'")
        cur.execute("DELETE FROM assignment_submissions WHERE student_email = 'test_student@sysrealm.com'")
        conn.commit()
        conn.close()

    def tearDown(self):
        conn = _get_sqlite_mirror()
        cur = conn.cursor()
        cur.execute("DELETE FROM student_xp_awards WHERE student_email = 'test_student@sysrealm.com'")
        cur.execute("DELETE FROM assignment_submissions WHERE student_email = 'test_student@sysrealm.com'")
        conn.commit()
        conn.close()
        self.app_context.pop()

    def _login_as_teacher(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = 'test_teacher@sysrealm.com'
            sess['user_name'] = 'Prof. Test Instructor'
            sess['account_type'] = 'teacher'

    def _login_as_student(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = 'test_student@sysrealm.com'
            sess['user_name'] = 'Test Student'
            sess['account_type'] = 'student'

    # ──────────────────────────────────────────────────────────────────────────
    # 1. WORKLOAD VALIDATION UNIT TESTS
    # ──────────────────────────────────────────────────────────────────────────

    def test_workload_validation_valid(self):
        workload = isolated_scheduler.get_example_workload()
        is_valid, err_msg, cleaned = isolated_scheduler.validate_workload(workload)
        self.assertTrue(is_valid)
        self.assertIsNone(err_msg)
        self.assertEqual(len(cleaned), 5)
        self.assertEqual(cleaned[0]['pid'], 'P1')
        self.assertEqual(cleaned[0]['burst_time'], 8)

    def test_workload_validation_empty_and_overflow(self):
        is_valid, err_msg, _ = isolated_scheduler.validate_workload([])
        self.assertFalse(is_valid)
        self.assertIn('at least 1 process', err_msg)

        # > 20 processes
        overflow = [{'pid': f'P{i}', 'burst_time': 2, 'arrival_time': 0, 'priority': 1} for i in range(25)]
        is_valid, err_msg, _ = isolated_scheduler.validate_workload(overflow)
        self.assertFalse(is_valid)
        self.assertIn('cannot exceed 20', err_msg)

    def test_workload_validation_duplicate_pid(self):
        dup = [
            {'pid': 'P1', 'burst_time': 4, 'arrival_time': 0, 'priority': 1},
            {'pid': 'P1', 'burst_time': 3, 'arrival_time': 1, 'priority': 2}
        ]
        is_valid, err_msg, _ = isolated_scheduler.validate_workload(dup)
        self.assertFalse(is_valid)
        self.assertIn('Duplicate Process ID', err_msg)

    def test_workload_validation_negative_arrival_and_burst(self):
        neg_arr = [{'pid': 'P1', 'burst_time': 4, 'arrival_time': -2, 'priority': 1}]
        is_valid, err_msg, _ = isolated_scheduler.validate_workload(neg_arr)
        self.assertFalse(is_valid)
        self.assertIn('negative arrival time', err_msg)

        zero_burst = [{'pid': 'P1', 'burst_time': 0, 'arrival_time': 0, 'priority': 1}]
        is_valid, err_msg, _ = isolated_scheduler.validate_workload(zero_burst)
        self.assertFalse(is_valid)
        self.assertIn('invalid burst time', err_msg)

    def test_workload_validation_invalid_priority(self):
        bad_prio = [{'pid': 'P1', 'burst_time': 4, 'arrival_time': 0, 'priority': 15}]
        is_valid, err_msg, _ = isolated_scheduler.validate_workload(bad_prio)
        self.assertFalse(is_valid)
        self.assertIn('must be between 1 and 10', err_msg)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. ISOLATED SIMULATION & OBJECTIVE EVALUATION TESTS
    # ──────────────────────────────────────────────────────────────────────────

    def test_isolated_simulation_does_not_mutate_global_state(self):
        workload = isolated_scheduler.get_example_workload()
        initial_procs_count = len(engine.process_manager.processes)
        initial_score = engine.score

        # Run simulation in isolation
        sim_res = isolated_scheduler.run_isolated_simulation(workload, 'RoundRobin', quantum=2)
        self.assertTrue(sim_res['success'])
        self.assertEqual(sim_res['algorithm'], 'RoundRobin')
        self.assertIn('metrics', sim_res)
        self.assertIn('gantt_chart', sim_res)
        self.assertTrue(len(sim_res['gantt_chart']) > 0)

        # Confirm global state was completely untouched
        self.assertEqual(len(engine.process_manager.processes), initial_procs_count)
        self.assertEqual(engine.score, initial_score)

    def test_evaluate_workload_objective_and_ties(self):
        workload = isolated_scheduler.get_example_workload()
        allowed = ['FCFS', 'SJF', 'Priority', 'RoundRobin']

        # Evaluate min average waiting time
        res_wt = isolated_scheduler.evaluate_workload_objective(workload, allowed, 'min_avg_waiting_time')
        self.assertEqual(res_wt['objective'], 'min_avg_waiting_time')
        self.assertIn('best_algorithms', res_wt)
        self.assertIn('SJF', res_wt['best_algorithms'])

        # Evaluate min average response time (RR should shine with low quantum)
        res_rt = isolated_scheduler.evaluate_workload_objective(workload, allowed, 'min_avg_response_time', quantum=2)
        self.assertIn('RoundRobin', res_rt['best_algorithms'])

        # Test tie tolerance: Single process workload where all algorithms yield identical metrics
        tie_workload = [{'pid': 'P1', 'name': 'Only Task', 'app_name': 'App', 'arrival_time': 0, 'burst_time': 5, 'priority': 1}]
        res_tie = isolated_scheduler.evaluate_workload_objective(tie_workload, ['FCFS', 'SJF', 'Priority'], 'min_avg_waiting_time')
        self.assertIn('FCFS', res_tie['best_algorithms'])
        self.assertIn('SJF', res_tie['best_algorithms'])
        self.assertIn('Priority', res_tie['best_algorithms'])

    # ──────────────────────────────────────────────────────────────────────────
    # 3. END-TO-END API INTEGRATION TESTS
    # ──────────────────────────────────────────────────────────────────────────

    def test_teacher_publish_virtual_apps_assignment_and_validation(self):
        self._login_as_teacher()

        # Valid challenge publication
        workload = isolated_scheduler.get_example_workload()
        payload = {
            'title': 'Test Challenge: Minimize Virtual Apps Waiting Time',
            'description': 'Identify whether SJF or FCFS minimizes waiting time for this interactive app workload.',
            'target_panel': 'virtual_apps',
            'points': 75,
            'workload': workload,
            'allowed_algorithms': ['FCFS', 'SJF', 'RoundRobin'],
            'optimization_objective': 'min_avg_waiting_time',
            'round_robin_quantum': 2
        }

        res = self.client.post('/api/teacher/assignments', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        assignment_id = data['assignment_id']
        self.assertIsNotNone(assignment_id)

        # Invalid publication: invalid burst time
        bad_payload = dict(payload)
        bad_payload['title'] = 'Invalid Challenge'
        bad_payload['workload'] = [{'pid': 'P1', 'burst_time': -5, 'arrival_time': 0, 'priority': 1}]
        res_bad = self.client.post('/api/teacher/assignments', json=bad_payload)
        self.assertEqual(res_bad.status_code, 400)
        self.assertFalse(res_bad.get_json()['success'])

        # Clean up created assignment
        self.client.delete(f'/api/teacher/assignments/{assignment_id}')

    def test_generic_completion_endpoint_rejects_virtual_apps(self):
        self._login_as_teacher()
        workload = isolated_scheduler.get_example_workload()
        create_res = self.client.post('/api/teacher/assignments', json={
            'title': 'Bypass Prevention Challenge',
            'target_panel': 'virtual_apps',
            'points': 50,
            'workload': workload,
            'allowed_algorithms': ['FCFS', 'SJF'],
            'optimization_objective': 'min_avg_waiting_time'
        })
        asgn_id = create_res.get_json()['assignment_id']

        # Switch to student and attempt calling generic completion endpoint
        self._login_as_student()
        bypass_res = self.client.post(f'/api/assignments/{asgn_id}/complete')
        self.assertEqual(bypass_res.status_code, 400)
        data = bypass_res.get_json()
        self.assertFalse(data['success'])
        self.assertIn('Virtual Apps Scheduling Challenges require algorithm evaluation', data['error'])

        # Clean up
        self._login_as_teacher()
        self.client.delete(f'/api/teacher/assignments/{asgn_id}')

    def test_student_assignment_flow_simulation_and_submission(self):
        # 1. Teacher creates Virtual Apps Challenge
        self._login_as_teacher()
        workload = isolated_scheduler.get_example_workload()
        create_res = self.client.post('/api/teacher/assignments', json={
            'title': 'Student Flow Benchmark: Shortest Waiting Time',
            'description': 'Find the algorithm yielding lowest waiting time.',
            'target_panel': 'virtual_apps',
            'points': 65,
            'workload': workload,
            'allowed_algorithms': ['FCFS', 'SJF', 'Priority', 'RoundRobin'],
            'optimization_objective': 'min_avg_waiting_time',
            'round_robin_quantum': 2
        })
        asgn_id = create_res.get_json()['assignment_id']

        # 2. Student fetches assignment details
        self._login_as_student()
        get_res = self.client.get(f'/api/assignments/{asgn_id}/virtual-apps')
        self.assertEqual(get_res.status_code, 200)
        asgn_data = get_res.get_json()['assignment']
        self.assertEqual(asgn_data['id'], asgn_id)
        self.assertEqual(len(asgn_data['workload']), 5)
        self.assertEqual(asgn_data['optimization_objective'], 'min_avg_waiting_time')

        # 3. Student runs isolated algorithm simulations
        run_res = self.client.post(f'/api/assignments/{asgn_id}/virtual-apps/run', json={'algorithm': 'SJF'})
        self.assertEqual(run_res.status_code, 200)
        run_data = run_res.get_json()
        self.assertTrue(run_data['success'])
        self.assertEqual(run_data['algorithm'], 'SJF')
        self.assertIn('metrics', run_data)
        self.assertIn('gantt_chart', run_data)

        # Unpermitted algorithm test
        unpermitted_res = self.client.post(f'/api/assignments/{asgn_id}/virtual-apps/run', json={'algorithm': 'UNKNOWN_ALGO'})
        self.assertEqual(unpermitted_res.status_code, 400)

        # 4. Student submits suboptimal algorithm (e.g. FCFS) -> Should fail verification with diagnostic feedback
        submit_bad = self.client.post(f'/api/assignments/{asgn_id}/virtual-apps/submit', json={
            'selected_algo': 'FCFS',
            'student_explanation': 'I guessed First Come First Served.'
        })
        self.assertEqual(submit_bad.status_code, 200)
        bad_data = submit_bad.get_json()
        self.assertFalse(bad_data['is_correct'])
        self.assertEqual(bad_data['xp_awarded'], 0)
        self.assertEqual(bad_data['attempts_count'], 1)
        self.assertIn('feedback', bad_data)
        self.assertIn('SJF', bad_data['best_algorithms'])

        # 5. Student retries with optimal algorithm (SJF) -> Should succeed and award XP
        from app import _user_engines
        student_engine = _user_engines.get('test_student@sysrealm.com')
        initial_score = student_engine.score if student_engine else 0
        submit_good = self.client.post(f'/api/assignments/{asgn_id}/virtual-apps/submit', json={
            'selected_algo': 'SJF',
            'student_explanation': 'Shortest Job First schedules shortest burst times first, mathematically minimizing average waiting time.'
        })
        self.assertEqual(submit_good.status_code, 200)
        good_data = submit_good.get_json()
        self.assertTrue(good_data['is_correct'])
        self.assertEqual(good_data['xp_awarded'], 65)
        self.assertEqual(good_data['attempts_count'], 2)
        student_engine = _user_engines.get('test_student@sysrealm.com')
        self.assertIsNotNone(student_engine)
        self.assertEqual(student_engine.score, initial_score + 65)

        # 6. Student submits again (Retry after winning) -> Idempotency: XP should NOT be awarded twice!
        score_after_win = student_engine.score
        submit_retry = self.client.post(f'/api/assignments/{asgn_id}/virtual-apps/submit', json={
            'selected_algo': 'SJF',
            'student_explanation': 'Confirming previous victory.'
        })
        self.assertEqual(submit_retry.status_code, 200)
        retry_data = submit_retry.get_json()
        self.assertTrue(retry_data['is_correct'])
        self.assertEqual(retry_data['xp_awarded'], 0)  # No duplicate points!
        self.assertEqual(student_engine.score, score_after_win)  # Score remains unchanged
        self.assertEqual(retry_data['attempts_count'], 3)

        # 7. Teacher views gradebook to verify LEFT JOIN submission row
        self._login_as_teacher()
        gradebook_res = self.client.get('/api/assignments')
        self.assertEqual(gradebook_res.status_code, 200)
        g_data = gradebook_res.get_json()
        teacher_rows = g_data['teacher_join_rows']
        student_submission_row = next((r for r in teacher_rows if r.get('assignment_id') == asgn_id and r.get('student_email') == 'test_student@sysrealm.com'), None)
        self.assertIsNotNone(student_submission_row)
        self.assertEqual(student_submission_row['selected_algo'], 'SJF')
        self.assertEqual(student_submission_row['score_awarded'], 65)
        self.assertEqual(student_submission_row['attempts_count'], 3)

        # Clean up
        self.client.delete(f'/api/teacher/assignments/{asgn_id}')


if __name__ == '__main__':
    unittest.main()
