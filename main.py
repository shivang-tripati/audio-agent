import sys

if __name__ == "__main__":
    if "--worker" in sys.argv:
        from worker_main import run_worker
        run_worker()
    else:
        from supervisor import run_supervisor
        run_supervisor()