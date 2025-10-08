# Simple LAN CBT Platform

## Overview
Minimal Computer-Based Testing platform designed to run on a local network (LAN/WiFi).
- Server: Flask (Python)
- Database: SQLite
- Frontend: HTML + JS (served by Flask)

## Features
- Admin interface to create exams and questions (MCQ).
- Start an exam session and get a local URL for students.
- Students open the exam page in a browser on the same LAN and take the test.
- Auto-grading for multiple-choice, save results, export CSV.
- Auto-submit when time runs out and basic fullscreen lock.

## Quick start
1. Install Python 3.10+ and pip.
2. Create and activate a virtualenv (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate
