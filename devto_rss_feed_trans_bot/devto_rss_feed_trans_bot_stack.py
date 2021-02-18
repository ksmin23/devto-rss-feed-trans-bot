#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
# vim: tabstop=2 shiftwidth=2 softtabstop=2 expandtab

from aws_cdk import (
  core,
  aws_dynamodb as dynamodb,
  aws_ec2,
  aws_events,
  aws_events_targets,
  aws_iam,
  aws_lambda as _lambda,
  aws_logs,
  aws_s3 as s3
)


class DevtoRssFeedTransBotStack(core.Stack):

  def __init__(self, scope: core.Construct, construct_id: str, **kwargs) -> None:
    super().__init__(scope, construct_id, **kwargs)

    # The code that defines your stack goes here
    vpc_name = self.node.try_get_context("vpc_name")
    vpc = aws_ec2.Vpc.from_lookup(self, "ExistingVPC",
      is_default=True,
      vpc_name=vpc_name)

    DYNAMODB_TABLE_NAME = self.node.try_get_context('dynamodb_table_name')
    if DYNAMODB_TABLE_NAME:
      ddb_table = dynamodb.Table.from_table_name(self, "RssFeedDDBTable", DYNAMODB_TABLE_NAME)
    else:
      ddb_table = dynamodb.Table(self, "RssFeedDDBTable",
        table_name="DevtoPost",
        partition_key=dynamodb.Attribute(name="id", type=dynamodb.AttributeType.STRING),
        billing_mode=dynamodb.BillingMode.PROVISIONED,
        read_capacity=25,
        write_capacity=15,
        time_to_live_attribute="expired_at"
      )

      ddb_table.add_global_secondary_index(index_name='p_time-index',
        partition_key=dynamodb.Attribute(name="p_time", type=dynamodb.AttributeType.NUMBER),
        projection_type=dynamodb.ProjectionType.KEYS_ONLY
      )
      DYNAMODB_TABLE_NAME = ddb_table.table_name
    assert DYNAMODB_TABLE_NAME

    sg_rss_feed_trans_bot = aws_ec2.SecurityGroup(self, 'RssFeedTransBotSG',
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for rss feed trans bot',
      security_group_name='rss-feed-trans-bot'
    )
    core.Tags.of(sg_rss_feed_trans_bot).add('Name', 'rss-feed-trans-bot')

    s3_lib_bucket_name = self.node.try_get_context('lib_bucket_name')
    s3_lib_bucket = s3.Bucket.from_bucket_name(self, "LambdaLayerS3Bucket", s3_lib_bucket_name)

    lambda_lib_layer = _lambda.LayerVersion(self, "RssFeedTransBotLib",
      layer_version_name="devto_rss_feed_trans_bot-lib",
      compatible_runtimes=[_lambda.Runtime.PYTHON_3_7],
      code=_lambda.Code.from_bucket(s3_lib_bucket, "var/devto_rss_feed_trans_bot-lib.zip")
    )

    lambda_fn_env = {
      'REGION_NAME': core.Aws.REGION,
      'TRANS_SRC_LANG': self.node.try_get_context('trans_src_lang'),
      'TRANS_DEST_LANG': self.node.try_get_context('trans_dest_lang'),
      'DRY_RUN': self.node.try_get_context('dry_run'),
      'DYNAMODB_TABLE_NAME': DYNAMODB_TABLE_NAME
    }

    #XXX: Deploy lambda in VPC - https://github.com/aws/aws-cdk/issues/1342
    rss_feed_trans_bot_lambda_fn = _lambda.Function(self, 'RssFeedTransBot',
      runtime=_lambda.Runtime.PYTHON_3_7,
      function_name='DevtoRssFeedTransBot',
      handler='rss_feed_trans_bot.lambda_handler',
      description='Translate rss feed of Devto/AWS Builders',
      code=_lambda.Code.asset('./src/main/python/RssFeedTransBot'),
      environment=lambda_fn_env,
      timeout=core.Duration.minutes(15),
      layers=[lambda_lib_layer],
      security_groups=[sg_rss_feed_trans_bot],
      vpc=vpc
    )

    ddb_table_rw_policy_statement = aws_iam.PolicyStatement(
      effect=aws_iam.Effect.ALLOW,
      resources=["*"], #XXX: You had better restrict to access only specific DynamoDB table
      actions=[
        "dynamodb:BatchGetItem",
        "dynamodb:Describe*",
        "dynamodb:List*",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:BatchWriteItem",
        "dynamodb:DeleteItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dax:Describe*",
        "dax:List*",
        "dax:GetItem",
        "dax:BatchGetItem",
        "dax:Query",
        "dax:Scan",
        "dax:BatchWriteItem",
        "dax:DeleteItem",
        "dax:PutItem",
        "dax:UpdateItem"
      ]
    )

    rss_feed_trans_bot_lambda_fn.add_to_role_policy(ddb_table_rw_policy_statement)

    translate_ro_policy = aws_iam.ManagedPolicy.from_managed_policy_arn(self,
      'TranslateReadOnly',
      'arn:aws:iam::aws:policy/TranslateReadOnly')
    rss_feed_trans_bot_lambda_fn.role.add_managed_policy(translate_ro_policy)

    comprehend_ro_policy = aws_iam.ManagedPolicy.from_managed_policy_arn(self,
      'ComprehendReadOnly',
      'arn:aws:iam::aws:policy/ComprehendReadOnly')
    rss_feed_trans_bot_lambda_fn.role.add_managed_policy(comprehend_ro_policy)

    # See https://docs.aws.amazon.com/lambda/latest/dg/tutorial-scheduled-events-schedule-expressions.html
    event_schedule = dict(zip(['minute', 'hour', 'month', 'week_day', 'year'],
      self.node.try_get_context('event_schedule').split(' ')))

    scheduled_event_rule = aws_events.Rule(self, 'RssFeedScheduledRule',
      schedule=aws_events.Schedule.cron(**event_schedule))

    scheduled_event_rule.add_target(aws_events_targets.LambdaFunction(rss_feed_trans_bot_lambda_fn))

    log_group = aws_logs.LogGroup(self, 'RssFeedTransBotLogGroup',
      log_group_name='/aws/lambda/DevtoRssFeedTransBot',
      retention=aws_logs.RetentionDays.THREE_DAYS)
    log_group.grant_write(rss_feed_trans_bot_lambda_fn)

    #core.CfnOutput(self, 'StackName', value=self.stack_name, export_name='StackName')
    #core.CfnOutput(self, 'VpcId', value=vpc.vpc_id, export_name='VpcId')
    core.CfnOutput(self, 'DynamoDBTableName', value=ddb_table.table_name, export_name='DynamoDBTableName')
    core.CfnOutput(self, 'LambdaFunctionName', value=rss_feed_trans_bot_lambda_fn.function_name,
      export_name='LambdaFunctionName')
    core.CfnOutput(self, 'LambdaFunctionRole', value=rss_feed_trans_bot_lambda_fn.role.role_name,
      export_name='LambdaFunctionRole')
