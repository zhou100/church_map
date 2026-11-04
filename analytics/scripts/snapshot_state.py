"""Private R2 acceptance metadata, conditionally advanced only after dbt success."""
from datetime import datetime
import json
import re

from analytics.scripts.cloud_snapshot import GateError, VERSION, encoded, metadata
from scripts.muse_state_store import Store

PREFIX = 'analytics_private/v1/snapshot_gate'
KEY = PREFIX + '/accepted.json'
LIMIT = 16 * 1024


def previous_record(record):
    if record is None:
        return None
    if (record.get('gate_version') != VERSION or
            record.get('dbt_status') != 'success' or
            not re.fullmatch(r'[0-9a-f]{40}', record.get('revision', '')) or
            not re.fullmatch(r'[0-9a-f]{64}', record.get('sha256', '')) or
            type(record.get('expected_rows')) is not int or record['expected_rows'] <= 0):
        raise GateError('invalid_accepted_metadata')
    timestamp = datetime.fromisoformat(record['taken_at'])
    if timestamp.tzinfo is None:
        raise GateError('invalid_accepted_timestamp')
    return (record['identity'], record['scope'], record['expected_rows'], timestamp)


class AcceptanceStore(Store):
    def read(self):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=KEY)
        except Exception as error:
            # Authorization/server failures are NOT an absent baseline.
            if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'NoSuchKey':
                return None, None
            raise
        body = response['Body']
        try:
            data = body.read(LIMIT + 1)
        finally:
            body.close()
        if len(data) > LIMIT or not response.get('ETag'):
            raise GateError('invalid_state_object')
        record = json.loads(data)
        if not isinstance(record, dict):
            raise GateError('invalid_accepted_metadata')
        previous_record(record)
        return record, response['ETag']

    def accept(self, snapshot, etag, run_id, revision, as_of_date):
        if not re.fullmatch(r'[0-9a-f]{32}', run_id) or not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise GateError('invalid_run_identity')
        record = {**metadata(snapshot), 'run_id': run_id, 'revision': revision,
                  'as_of_date': as_of_date, 'dbt_status': 'success'}
        data = encoded(record)
        # Immutable build receipt first; it is not itself the accepted pointer.
        self.put_once(f'{PREFIX}/runs/{run_id}.json', data)
        condition = {'IfMatch': etag} if etag is not None else {'IfNoneMatch': '*'}
        # Never retry a conflict unconditionally. An ambiguous network response
        # must be reconciled by reading accepted.json/run_id before rerunning.
        self.client.put_object(Bucket=self.bucket, Key=KEY, Body=data,
                               ContentType='application/json', **condition)
        return record
