resource "aws_vpc" "retail" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${local.name}-vpc" }
  lifecycle {
    precondition {
      condition     = local.account_id == var.expected_account_id
      error_message = "Active AWS identity does not match the reviewed competition account."
    }
    precondition {
      condition     = length(data.aws_availability_zones.available.names) >= 2
      error_message = "Two available AZs are required; do not silently remove redundancy."
    }
  }
}

resource "aws_subnet" "application" {
  count                   = 2
  vpc_id                  = aws_vpc.retail.id
  cidr_block              = cidrsubnet(aws_vpc.retail.cidr_block, 8, 10 + count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false
  tags                    = { Name = "${local.name}-app-${count.index + 1}" }
}

resource "aws_subnet" "database" {
  count                   = 2
  vpc_id                  = aws_vpc.retail.id
  cidr_block              = cidrsubnet(aws_vpc.retail.cidr_block, 8, 20 + count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false
  tags                    = { Name = "${local.name}-db-${count.index + 1}" }
}

resource "aws_route_table" "application" {
  vpc_id = aws_vpc.retail.id
  route  = []
  tags   = { Name = "${local.name}-app-isolated" }
}
resource "aws_route_table" "database" {
  vpc_id = aws_vpc.retail.id
  route  = []
  tags   = { Name = "${local.name}-db-isolated" }
}
resource "aws_route_table_association" "application" {
  count          = 2
  subnet_id      = aws_subnet.application[count.index].id
  route_table_id = aws_route_table.application.id
}
resource "aws_route_table_association" "database" {
  count          = 2
  subnet_id      = aws_subnet.database[count.index].id
  route_table_id = aws_route_table.database.id
}

# No Internet Gateway, NAT Gateway, public subnet, or default internet route.
# CloudWatch logging is supplied by Lambda's service integration, not SDK calls
# from this VPC. IAM DB token generation is local SigV4 signing, no STS endpoint.
