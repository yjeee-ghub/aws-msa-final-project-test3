locals {
  # Execute Python directly: cmd /C interprets quoted paths differently on Windows.
  # Paths and user values travel in the environment, never as shell fragments.
  readiness_python_command = "import os, runpy, sys; sys.argv = [os.environ['FINAL_CHECK_SCRIPT'], '--cluster', os.environ['FINAL_CHECK_CLUSTER'], '--profile', os.environ['FINAL_CHECK_PROFILE'], '--region', os.environ['FINAL_CHECK_REGION']]; sys.path.insert(0, os.path.dirname(sys.argv[0])); runpy.run_path(sys.argv[0], run_name='__main__')"
  readiness_environment = {
    FINAL_CHECK_CLUSTER = var.cluster_name
    FINAL_CHECK_PROFILE = var.aws_profile
    FINAL_CHECK_REGION  = var.aws_region
  }
}
