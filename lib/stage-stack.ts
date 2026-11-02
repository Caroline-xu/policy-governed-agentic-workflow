import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import { Construct } from 'constructs';
import * as fs from 'fs';
import * as path from 'path';

const NODE_IDS = ['N01', 'N02', 'N03', 'N04', 'N05', 'N06', 'N07', 'N08', 'N09'];
// Decision table: only these nodes may call Bedrock, each with its own prompt.
const MODEL_NODES = new Set(['N01', 'N03', 'N04', 'N05', 'N06', 'N08', 'N09']);
const BEDROCK_MODEL_ID = 'us.anthropic.claude-haiku-4-5-20251001-v1:0';

// Works from lib/ (ts-node) and from dist/lib/ (compiled): walk up until the
// directory that contains both lambda/ and state_machine/.
function repoRoot(): string {
  let dir = __dirname;
  for (let i = 0; i < 5; i++) {
    if (fs.existsSync(path.join(dir, 'lambda')) && fs.existsSync(path.join(dir, 'state_machine'))) {
      return dir;
    }
    dir = path.dirname(dir);
  }
  throw new Error('Could not locate repo root (lambda/ + state_machine/)');
}

export class StageStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // --- Storage -------------------------------------------------------------
    const intakeBucket = new s3.Bucket(this, 'CaseIntakeBucket', {
      versioned: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY, // assignment teardown requirement
      autoDeleteObjects: true,
    });

    // One item per node ATTEMPT (Part 2 audit fields). PK case_id, SK
    // attempt_key = "<execution_id>#<node_id>#<attempt>".
    const auditTable = new dynamodb.Table(this, 'AuditTable', {
      partitionKey: { name: 'case_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'attempt_key', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const decisionTable = new dynamodb.Table(this, 'DecisionTable', {
      partitionKey: { name: 'case_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // --- Lambdas: one per action node (independent IAM + prompt versions) ---
    const lambdaCode = lambda.Code.fromAsset(path.join(repoRoot(), 'lambda'));
    const nodeFunctions: Record<string, lambda.Function> = {};
    for (const nodeId of NODE_IDS) {
      const fn = new lambda.Function(this, `${nodeId}Function`, {
        runtime: lambda.Runtime.PYTHON_3_12,
        code: lambdaCode,
        handler: `${nodeId.toLowerCase()}.handler`,
        timeout: cdk.Duration.seconds(60),
        environment: {
          NODE_MODE: 'model', // Bedrock access verified 2026-10-23 via the us. inference profile
          BEDROCK_MODEL_ID,
          AUDIT_TABLE_NAME: auditTable.tableName,
        },
        description: `STAGE action node ${nodeId} (skeleton)`,
      });
      auditTable.grantWriteData(fn);
      if (MODEL_NODES.has(nodeId)) {
        fn.addToRolePolicy(new iam.PolicyStatement({
          actions: ['bedrock:InvokeModel', 'bedrock:Converse'],
          // Least privilege: this inference profile, plus the foundation
          // model it may route to in each US profile region.
          resources: [
            `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/${BEDROCK_MODEL_ID}`,
            `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`,
            `arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`,
            `arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`,
          ],
        }));
      }
      nodeFunctions[nodeId] = fn;
    }

    const terminalFunction = new lambda.Function(this, 'TerminalFunction', {
      runtime: lambda.Runtime.PYTHON_3_12,
      code: lambdaCode,
      handler: 'terminal.handler',
      timeout: cdk.Duration.seconds(30),
      environment: { DECISION_TABLE_NAME: decisionTable.tableName },
      description: 'Writes the final decision record for terminal states T01-T10 (infrastructure, not a decision node)',
    });
    decisionTable.grantWriteData(terminalFunction);

    // H01 evaluation simulator: supplies simulated_adjuster_decision by calling
    // SendTaskSuccess. It is NOT the human decision and NOT a graph node.
    const simulatorFunction = new lambda.Function(this, 'H01SimulatorFunction', {
      runtime: lambda.Runtime.PYTHON_3_12,
      code: lambdaCode,
      handler: 'h01_simulator.handler',
      timeout: cdk.Duration.seconds(30),
      description: 'Evaluation-only: resumes H01 with the test case simulated_adjuster_decision',
    });

    // --- State machine -------------------------------------------------------
    // Route chosen for the skeleton (documented in README): the frozen graph is
    // an ASL JSON file (state_machine/definition.asl.json), loaded here and
    // bound to resource ARNs via DefinitionSubstitutions. One artifact to diff
    // and review per graph version; a policy change = a new version of this
    // file deployed as a new state machine version, never an in-place edit.
    const asl = fs.readFileSync(
      path.join(repoRoot(), 'state_machine', 'definition.asl.json'), 'utf8');

    const smRole = new iam.Role(this, 'StateMachineRole', {
      assumedBy: new iam.ServicePrincipal('states.amazonaws.com'),
    });
    const substitutions: Record<string, string> = {
      TerminalLambdaArn: terminalFunction.functionArn,
      AuditTableName: auditTable.tableName,
    };
    for (const nodeId of NODE_IDS) {
      substitutions[`${nodeId}LambdaArn`] = nodeFunctions[nodeId].functionArn;
      nodeFunctions[nodeId].grantInvoke(smRole);
    }
    terminalFunction.grantInvoke(smRole);
    // H01 callback writes its task-token item to the audit table.
    smRole.addToPolicy(new iam.PolicyStatement({
      actions: ['dynamodb:PutItem'], resources: [auditTable.tableArn],
    }));

    const stateMachine = new sfn.CfnStateMachine(this, 'StageStateMachine', {
      stateMachineType: 'STANDARD', // H01 can pause for days; Express caps at 5 minutes
      definitionString: asl,
      definitionSubstitutions: substitutions,
      roleArn: smRole.roleArn,
      tracingConfiguration: { enabled: true }, // X-Ray (Part 4 observability)
    });

    simulatorFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['states:SendTaskSuccess'], resources: [stateMachine.attrArn],
    }));

    // --- Outputs ---------------------------------------------------------------
    new cdk.CfnOutput(this, 'IntakeBucketName', { value: intakeBucket.bucketName });
    new cdk.CfnOutput(this, 'AuditTableName', { value: auditTable.tableName });
    new cdk.CfnOutput(this, 'DecisionTableName', { value: decisionTable.tableName });
    new cdk.CfnOutput(this, 'StateMachineArn', { value: stateMachine.attrArn });
    new cdk.CfnOutput(this, 'H01SimulatorFunctionName', { value: simulatorFunction.functionName });
  }
}
