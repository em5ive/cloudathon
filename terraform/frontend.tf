resource "aws_s3_bucket" "frontend" {
  bucket        = "${local.name}-${local.account_id}-${var.aws_region}-frontend"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name}-s3-oac"
  description                       = "Signed CloudFront-only access to the private S3 REST origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_cache_policy" "static" {
  name        = "${local.name}-static"
  min_ttl     = 0
  default_ttl = 300
  max_ttl     = 3600
  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name = "${local.name}-security-headers"
  security_headers_config {
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false
      preload                    = false
      override                   = true
    }
    content_security_policy {
      content_security_policy = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' https://*.execute-api.${var.aws_region}.amazonaws.com https://*.auth.${var.aws_region}.amazoncognito.com; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; form-action 'self'"
      override                = true
    }
  }
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  comment             = "${local.name}: static frontend; API uses its default HTTPS execute-api origin directly"
  wait_for_deployment = true

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "private-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
    # The provider supplies the empty S3 API configuration for OAC. Explicitly
    # declaring a blank legacy OAI block causes a perpetual diff on readback.
  }

  default_cache_behavior {
    target_origin_id           = "private-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.static.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  viewer_certificate {
    cloudfront_default_certificate = true
    # AWS controls the default certificate's TLS behavior. Do not promise
    # custom-domain TLS policies without an approved domain/certificate.
  }
  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudFrontOACReadOnly"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.frontend.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn } }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.frontend.arn, "${aws_s3_bucket.frontend.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

resource "aws_s3_object" "frontend" {
  for_each      = local.site_files
  bucket        = aws_s3_bucket.frontend.id
  key           = each.key
  source        = "${path.module}/../frontend/${each.key}"
  source_hash   = filemd5("${path.module}/../frontend/${each.key}")
  content_type  = lookup(local.mime_types, element(reverse(split(".", each.key)), 0), "application/octet-stream")
  cache_control = endswith(each.key, ".html") ? "no-cache, max-age=0, must-revalidate" : "public, max-age=300"
  depends_on    = [aws_s3_bucket_ownership_controls.frontend, aws_s3_bucket_server_side_encryption_configuration.frontend]
}

resource "aws_s3_object" "frontend_config" {
  bucket        = aws_s3_bucket.frontend.id
  key           = "config.json"
  content_type  = "application/json"
  cache_control = "no-store, max-age=0"
  content = jsonencode({
    apiBaseUrl    = aws_apigatewayv2_api.retail.api_endpoint
    cognitoDomain = "https://${aws_cognito_user_pool_domain.customers.domain}.auth.${var.aws_region}.amazoncognito.com"
    clientId      = aws_cognito_user_pool_client.frontend.id
    userPoolId    = aws_cognito_user_pool.customers.id
    region        = var.aws_region
    redirectUri   = "https://${aws_cloudfront_distribution.frontend.domain_name}/"
  })
  depends_on = [aws_s3_bucket_ownership_controls.frontend, aws_s3_bucket_server_side_encryption_configuration.frontend]
}
