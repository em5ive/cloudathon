resource "aws_db_subnet_group" "retail" {
  name       = "${local.name}-database"
  subnet_ids = aws_subnet.database[*].id
}

resource "aws_rds_cluster_parameter_group" "retail" {
  name_prefix = "${local.name}-pg-"
  family      = "aurora-postgresql${split(".", var.aurora_engine_version)[0]}"
  description = "Require TLS from proxy to Aurora"
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
  # Disable routine SQL and bind-value logging. Error statement text can still
  # be logged by PostgreSQL; bootstrap must never embed a plaintext password.
  # These dynamic settings are supported by PostgreSQL 16 and 17.
  parameter {
    name         = "log_statement"
    value        = "none"
    apply_method = "immediate"
  }
  parameter {
    name         = "log_parameter_max_length"
    value        = "0"
    apply_method = "immediate"
  }
  parameter {
    name         = "log_parameter_max_length_on_error"
    value        = "0"
    apply_method = "immediate"
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_rds_cluster" "retail" {
  cluster_identifier              = "${local.name}-aurora-pg"
  engine                          = "aurora-postgresql"
  engine_mode                     = "provisioned"
  engine_version                  = var.aurora_engine_version
  database_name                   = local.db_name
  master_username                 = local.master_user
  manage_master_user_password     = true
  port                            = 5432
  storage_encrypted               = true
  storage_type                    = "aurora"
  db_subnet_group_name            = aws_db_subnet_group.retail.name
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.retail.name
  vpc_security_group_ids          = [aws_security_group.database.id]
  backup_retention_period         = 7
  preferred_backup_window         = "08:00-09:00"
  preferred_maintenance_window    = "sun:10:00-sun:11:00"
  copy_tags_to_snapshot           = true
  deletion_protection             = true
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${local.name}-final-reviewed-snapshot"
  apply_immediately               = false
  enabled_cloudwatch_logs_exports = ["postgresql"]

  serverlessv2_scaling_configuration {
    min_capacity = var.min_acu
    max_capacity = var.max_acu
  }

  lifecycle {
    prevent_destroy = true
    # Deliberate engine changes remain visible. No in-place MySQL conversion.
  }
}

resource "aws_rds_cluster_instance" "retail" {
  count                      = 2
  identifier                 = "${local.name}-pg-${count.index + 1}"
  cluster_identifier         = aws_rds_cluster.retail.id
  engine                     = aws_rds_cluster.retail.engine
  engine_version             = aws_rds_cluster.retail.engine_version
  instance_class             = "db.serverless"
  availability_zone          = local.azs[count.index]
  db_subnet_group_name       = aws_db_subnet_group.retail.name
  publicly_accessible        = false
  promotion_tier             = count.index
  auto_minor_version_upgrade = true
  apply_immediately          = false
  copy_tags_to_snapshot      = true
}

resource "aws_secretsmanager_secret" "application" {
  name                    = "${local.name}/database/application"
  description             = "Initialized inside the VPC by approved bootstrap; no password in Terraform state"
  recovery_window_in_days = 7
  # No secret_version resource: bootstrap generates and stores credentials.
  lifecycle {
    prevent_destroy = true
  }
}
