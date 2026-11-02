#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { StageStack } from '../lib/stage-stack';

const app = new cdk.App();
new StageStack(app, 'PolicyWorkflowStack', {
  // Environment-agnostic on purpose for the skeleton: no account/region
  // lookups, so `cdk synth` works without AWS credentials. Pin env before
  // a real deploy (Bedrock availability/quota for Haiku 4.5 is regional).
  description: 'STAGE policy-governed agentic workflow on AWS',
});
