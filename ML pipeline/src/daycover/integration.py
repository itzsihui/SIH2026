"""Machine-readable integration boundary; this module never calls payment rails."""


PILOT_NAMESPACE = 'pilot'
DECISION_AUTHORITY = 'daycover.pilot'
SETTLEMENT_AUTHORITY = 'pilot_simulation_ledger'
SIMULATION_POLICY_STATE = 'enrolled_simulation'


def boundaries() -> dict:
    return {
        'schema_version': 1,
        'decision_authority': DECISION_AUTHORITY,
        'settlement_authority': SETTLEMENT_AUTHORITY,
        'execution_mode': 'simulation_only',
        'real_issuance_supported': False,
        'real_settlement_supported': False,
        'contract_lifecycles': ['research', 'candidate_proposal', 'approved', 'simulation'],
        'policy_states': {
            'indicative_quote': 'Does not create or approve coverage.',
            'enrolled_simulation': 'Customer accepted a supported simulation version; no real policy issued.',
            'issued_policy': 'Reserved for a separately authorized future issuance service; unavailable here.',
        },
        'identity_mapping': {
            'pilot': 'Existing SIM-POL identifiers retained; HC stall IDs are representative pilot centres.',
            'wallet_sandbox': 'Wallet IDs and balances remain external; never infer mapping from matching text.',
            'canonical_key': 'policy_id + product_version_id + policy_period_id',
            'adapter_requirement': 'Explicit persisted merchant/stall mapping and versioned read-only adapter before integration.',
            'wallet_bridge_enabled': False,
            'engine_local': 'LOCAL-STALL IDs bind persisted local merchant/operator/stall entities; identities remain unverified.',
            'mapping_state': 'Hashed opaque manual_local/wallet_sandbox references; independent local eligibility review required.',
        },
        'authentication': {
            'default_mode': 'local', 'provider': 'local_opaque_credentials',
            'real_identity_provider_connected': False,
            'demo_mode': 'DAYCOVER_AUTH_MODE=demo explicitly enables unauthenticated legacy HC scenarios on an isolated local database.',
            'transaction_connector_connected': False,
            'optional_sales_consent_required_for_fixed_cover': False,
        },
        'mock_settlement': {'available':True, 'provider':'deterministic_mock_settlement_v1', 'recipient_review_scope':'local_mock_only', 'external_wallet_bridge':False, 'real_rail_enabled':False},
        'services': {
            'fastapi': 'Owns accepted simulation terms and deterministic pilot decisions.',
            'wallet_gateway': 'Preserved research sandbox; no authority over pilot caps or settlement.',
            'historical_replay': 'Read-only research result; no payable-instruction authority.',
            'ml': 'Advisory features/recommendations; no in-force contract writes.',
            'provider_adapter': 'Local deterministic mock settlement/outbox only; real adapters disabled; cannot reprice or resize a benefit.',
        },
    }
