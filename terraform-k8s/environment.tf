locals { environment = jsondecode(file("${path.module}/../scripts/ops/environment.json")) }
