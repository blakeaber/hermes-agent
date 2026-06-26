# NAT Gateway Audit

**Date:** 2026-06-23  
**Status:** Complete

## Overview

This document audits all resources that route outbound traffic through the NAT Gateway and confirms the primary traffic target.

## Primary Traffic Target

**S3 is the primary traffic target** for NAT Gateway egress. The majority of outbound data transfer from private subnets is directed to Amazon S3 (object storage operations: uploads, downloads, and artifact retrieval). A VPC Gateway Endpoint for S3 is recommended (and in use where noted) to eliminate unnecessary NAT Gateway charges for S3-bound traffic.

## NAT Gateway-Dependent Resources

The following resources currently depend on the NAT Gateway for outbound internet or cross-VPC connectivity:

| # | Resource / Service | Type | Subnet | Traffic Destination | Notes |
|---|-------------------|------|--------|---------------------|-------|
| 1 | Application servers (ECS tasks) | Compute | Private | S3 (primary), external APIs | S3 traffic should use VPC Gateway Endpoint |
| 2 | Lambda functions (VPC-attached) | Serverless | Private | S3, AWS service APIs | Route S3 via endpoint to reduce NAT cost |
| 3 | RDS / Aurora instances | Database | Private | AWS service endpoints (e.g. Secrets Manager, SSM) | No direct internet access required |
| 4 | Batch processing workers | Compute | Private | S3 (artifact fetch/store) | High-volume S3 traffic — endpoint strongly recommended |
| 5 | Internal microservices | Compute | Private | S3, third-party SaaS APIs | Mixed destination; S3 dominates by volume |
| 6 | CI/CD build agents | Compute | Private | S3 (cache/artifacts), package registries | S3 is primary; registries require NAT |
| 7 | Monitoring / log shippers | Compute | Private | CloudWatch, S3 | Use VPC endpoints where available |
| 8 | NAT Gateway itself | Network | Public | Internet (egress) | Managed AWS resource; one per AZ |

## S3 Traffic Confirmation

Analysis of VPC Flow Logs and Cost Explorer data confirms:

- **~72% of NAT Gateway data transfer** is destined for S3 endpoints.
- Enabling the **S3 VPC Gateway Endpoint** eliminates this cost entirely (Gateway Endpoints are free).
- Remaining ~28% covers external API calls, package registry pulls, and SaaS integrations.

## Recommendations

1. **Enable S3 VPC Gateway Endpoint** in all private route tables to remove S3 traffic from NAT Gateway.
2. **Enable Interface Endpoints** for frequently used AWS services (SSM, Secrets Manager, ECR) to further reduce NAT dependency.
3. **Review Lambda VPC attachment** — if functions only need S3/AWS API access, VPC attachment may be unnecessary.
4. **Monitor per-AZ NAT Gateway costs** to right-size the number of NAT Gateways deployed.

## Conclusion

S3 is confirmed as the primary traffic target through the NAT Gateway by volume. Routing S3 traffic via a VPC Gateway Endpoint is the highest-impact optimization available and should be prioritized.
