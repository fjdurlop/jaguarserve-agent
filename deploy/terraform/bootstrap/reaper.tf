# Reaper: safety net for a forgotten lab cluster. Every 30 min it looks for EKS clusters tagged
# `lab-expires-at` (set by `make up`) that are past that time and tears down what bills: GPU and system
# instances first, then node groups, then the cluster. `make down` still runs afterwards to clean the
# Terraform state and anything Kubernetes created (load balancers, volumes).

data "archive_file" "reaper" {
  type        = "zip"
  source_file = "${path.module}/reaper/reaper.py"
  output_path = "${path.module}/.build/reaper.zip"
}

resource "aws_iam_role" "reaper" {
  name = "${var.name}-reaper"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "reaper_logs" {
  role       = aws_iam_role.reaper.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "reaper" {
  name = "reap-expired-lab-clusters"
  role = aws_iam_role.reaper.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["eks:ListClusters", "eks:DescribeCluster", "eks:ListNodegroups", "ec2:DescribeInstances"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["eks:DeleteNodegroup", "eks:DeleteCluster"]
        Resource = "*"
        Condition = {
          StringEquals = { "aws:ResourceTag/project" = var.name }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:TerminateInstances"]
        Resource = "*"
        Condition = {
          StringEquals = { "aws:ResourceTag/project" = var.name }
        }
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "reaper" {
  name              = "/aws/lambda/${var.name}-reaper"
  retention_in_days = 14
}

resource "aws_lambda_function" "reaper" {
  function_name    = "${var.name}-reaper"
  role             = aws_iam_role.reaper.arn
  runtime          = "python3.12"
  handler          = "reaper.handler"
  filename         = data.archive_file.reaper.output_path
  source_code_hash = data.archive_file.reaper.output_base64sha256
  timeout          = 120
  environment {
    variables = { PROJECT_TAG = var.name, DRY_RUN = "false" }
  }
  depends_on = [aws_cloudwatch_log_group.reaper]
}

resource "aws_cloudwatch_event_rule" "reaper" {
  name                = "${var.name}-reaper"
  schedule_expression = "rate(30 minutes)"
}

resource "aws_cloudwatch_event_target" "reaper" {
  rule = aws_cloudwatch_event_rule.reaper.name
  arn  = aws_lambda_function.reaper.arn
}

resource "aws_lambda_permission" "reaper" {
  statement_id  = "events"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reaper.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.reaper.arn
}
