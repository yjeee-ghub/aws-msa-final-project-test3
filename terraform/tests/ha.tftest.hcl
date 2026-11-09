# Provider is fully mocked. These tests never create real AWS resources.
mock_provider "aws" {}

run "two_az_local_nat_paths" {
  command = apply
  module {
    source = "./network"
  }
  variables {
    vpc_cidr             = "10.42.0.0/16"
    vpc_name             = "offline-ha-test"
    igw_name             = "offline-ha-test-igw"
    availability_zones   = ["ap-northeast-2a", "ap-northeast-2c"]
    public_subnet_cidrs  = ["10.42.1.0/24", "10.42.2.0/24"]
    private_subnet_cidrs = ["10.42.11.0/24", "10.42.12.0/24"]
    db_subnet_cidrs      = ["10.42.21.0/24", "10.42.22.0/24"]
  }
  assert {
    condition     = length(aws_nat_gateway.main) == 2 && length(aws_eip.nat) == 2
    error_message = "Initial creation must include two NATs and two EIPs."
  }
  assert {
    condition = alltrue([for i in range(2) :
      aws_nat_gateway.main[i].subnet_id == aws_subnet.public[i].id &&
      aws_route.private_nat[i].nat_gateway_id == aws_nat_gateway.main[i].id &&
      aws_route_table_association.private[i].route_table_id == aws_route.private_nat[i].route_table_id &&
      aws_subnet.private[i].availability_zone == aws_subnet.public[i].availability_zone
    ])
    error_message = "Each app subnet must use the NAT in its own AZ."
  }
}

run "multi_az_private_database" {
  command = apply
  module {
    source = "./rds"
  }
  variables {
    project_name          = "offline-ha-test"
    vpc_id                = "vpc-offline"
    db_subnet_ids         = ["subnet-db-a", "subnet-db-c"]
    eks_security_group_id = "sg-offline"
    db_instance_class     = "db.t4g.micro"
    db_engine_version     = "8.4.11"
    db_password           = "offline-mock-not-a-real-password"
    manage_db_password    = true
  }
  assert {
    condition     = aws_db_instance.main.multi_az && !aws_db_instance.main.publicly_accessible && aws_db_instance.main.storage_encrypted
    error_message = "RDS must be Multi-AZ, private and encrypted on initial creation."
  }
}
