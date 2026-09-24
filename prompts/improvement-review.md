# Explicit improvement architecture review

Review only the user-triggered request identified by `request_digest`. Do not create a
feature request, alter the active implementation plan, approve the change, or enable a
capability. Return an `architecture_impact` proposal matching
`schemas/improvement-architecture-impact-v1.schema.json`; corrections must name the
immediately preceding revision digest. State any scope that exceeds the configured
bound so the supervisor can escalate it to the normal development cycle. A
self-development proposal may target only a successor generation in isolation and
must never activate or edit the executing controller generation.
