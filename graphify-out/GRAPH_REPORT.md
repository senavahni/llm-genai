# Graph Report - llm-genai  (2026-11-10)

## Corpus Check
- 303 files · ~157,413 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 29 file(s) not represented in the graph (top: .bat 17, (none) 7, .example 1)

## Summary
- 3657 nodes · 11485 edges · 161 communities (124 shown, 37 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 1045 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Model & Project Services
- Chat/Image Service Context
- Rate Limit & Quota
- Admin Catalog CRUD
- database.py
- Provider Base & Registry
- SSE Streaming
- Router Service & Fallback
- OVLLMBackend
- Usage Accounting
- Public API Controllers
- Device Manager
- Admin Keys & Schemas
- Runtime App State
- converters.py
- fake_genai.py
- UnifiedChunk
- Provider Adapter Tests
- Traefik Dynamic Config
- ORM Models Base
- Tool Call Parsers
- Gemini/Anthropic Message Mapping
- Admin Projects & Observe
- Retention Maintenance
- test_health_ready.py
- Logger & Redaction
- Model Download & Measure Scripts
- Traefik Static Config
- manage.py CLI
- Metrics & Runtime Health
- OpenAI Provider
- PRD Concepts
- Console Env Status
- OpenVINO Common Loading
- Tasks: Local Runtime & DB
- Image Controller
- Provider Billing
- OpenRouter Free Models
- Hardware E2E Tests
- Admin Console JS
- Image Input Handling
- API Key Service
- test_ov_embed.py
- OV LLM Tests
- Device Manager Tests
- OpenVINO Model Conversion
- Tasks: Routing & QA
- API v1 Integration Tests
- Framework Examples & Backup
- Tasks: Setup & Core
- Profile: full
- Tasks: Usage & API v1
- Seed Models: Models
- Error Handling Tests
- OV Diffusion Backend
- Backend Threading Helpers
- Profile: ram16
- config.py
- OV Diffusion Tests
- OpenAI SDK Examples
- Profile: remote-only
- Load Tests & Port Wait
- Admin Integration Tests
- Auth Integration Tests
- Hardware LLM Tests
- spike_embed.py
- Task list - LLM Gateway (PRD v2.0)
- Seed Models: Local Params
- DB Model Tests
- Tasks: Errors & Providers
- unified.py
- Model Memory Measurement
- App Factory & Test Setup
- OpenAI Provider Tests
- Admin Query Pagination
- Inference Service
- helper.py
- model_controller.py
- API Key Crypto
- asyncio
- Request Context Middleware
- Client Integration Docs
- runtime/core/lifespan.py
- Local Benchmarks
- Alembic Migrations
- Error Handler Middleware
- test_runtime_embed.py
- Admin Usage Verification
- Profile Integration Tests
- bench_embed.py
- models
- Release & DB Decisions
- NPU & FIM Model Notes
- Deployment Mode A & Device Budget
- Local Smoke Script
- test_priority.py
- Seed Models: Providers
- Client & Proxy Docs
- OV VLM Backend
- image_service.py
- Secret Scan Script
- observe.py
- Admin Runtime Routes
- Console Route
- Migrations Env
- JS SDK Example
- providers/conftest.py
- Usage Endpoint
- Admin API (/admin endpoints)
- Custom Provider Tests
- Hermes Tool Prompt
- Seed Models: Routes
- Admin Console Feature
- Any
- Admin Quota Routes
- Image2ImagePipeline
- .stream_generate
- SD1.5 img2img Smoke
- Admin Maintenance Routes
- SD1.5 txt2img Smoke
- Vision Smoke Input
- SD Component Devices
- .generate
- OpenVINO-only Decision
- Console Kit
- Usage Charts
- Test Layers & Quality Gate
- Stub: Release v1 acceptance criteria
- Stub: scripts/probe_devices.py
- Stub: llm_gateway
- test_helper.py
- Task v1.0.0 — LLM Gateway (Embedding Lokal OpenVINO GPU & Dukungan Market Intelligence)
- TASK-09 Hardware probe, model download/convert & measure
- Any
- test_live_providers.py
- Attempt
- TextEmbeddingPipeline
- OpenAI-compatible client integration (base URL /v1, lgw_ key, route as model)
- .mcp.json
- chat_completions
- _PerfMetrics
- test_usage_tags.py
- embedding_instructions

## God Nodes (most connected - your core abstractions)
1. `SessionLocal()` - 139 edges
2. `AuthContext` - 119 edges
3. `Request` - 116 edges
4. `ModelConfig` - 115 edges
5. `InvalidRequestError` - 88 edges
6. `get_settings()` - 87 edges
7. `LocalModelSpec` - 70 edges
8. `GatewayError` - 60 edges
9. `DeviceManager` - 59 edges
10. `RequestCtx` - 56 edges

## Surprising Connections (you probably didn't know these)
- `LGW-V1-02 — Backend runtime `openvino_embed`` --references--> `EmbeddingService`  [INFERRED]
  docs/v1.0.0/V1_TASKS.md → app/services/embedding_service.py
- `LGW-V1-01 — Spike ekspor & kesetaraan` --references--> `TextEmbeddingPipeline`  [INFERRED]
  docs/v1.0.0/V1_TASKS.md → tests/fakes/fake_genai.py
- `LGW-V1-02 — Backend runtime `openvino_embed`` --references--> `gpu()`  [INFERRED]
  docs/v1.0.0/V1_TASKS.md → tests/hardware/test_embed.py
- `body()` --indirect_call--> `gen()`  [INFERRED]
  app/controllers/common.py → tests/unit/test_errors.py
- `LGW-V1-03 — Profil `remote-embed-gpu`, whitelist, route, key` --references--> `local()`  [INFERRED]
  docs/v1.0.0/V1_TASKS.md → scripts/bench_embed.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Local model acquisition & catalog sync pipeline** — llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition_probe_devices, llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition_download_models, llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition_convert_openvino, llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition_measure_models, llm_gateway_docs_v2_tasks_task_04_database_models_migrations_seed_models_yaml, llm_gateway_docs_v2_tasks_task_04_database_models_migrations_manage_seed [EXTRACTED 1.00]
- **NVIDIA Nemotron free model family on OpenRouter** — docs_openrouter_nvidia_free_nemotron_3_ultra_550b_a55b, docs_openrouter_nvidia_free_nemotron_3_5_super_vl, docs_openrouter_nvidia_free_nemotron_3_5_lightning, docs_openrouter_nvidia_free_nemotron_3_nano_omni_30b_a3b_reasoning, docs_openrouter_nvidia_free_nemotron_3_5_content_safety [EXTRACTED 1.00]
- **Free OpenRouter models with no public standard endpoint or listed price** — docs_openrouter_dots_studio_free_dots_3_note_preview, docs_openrouter_north_mini_code_free_north_mini_code, docs_openrouter_nvidia_free_nemotron_3_nano_omni_30b_a3b_reasoning, docs_openrouter_recursive_free_flint_v1_0, docs_openrouter_xingchen_free_xing4_0_29b_a4b [EXTRACTED 1.00]
- **Device memory management (budget, pinning, eviction, event logging, no-CPU)** — llm_gateway_docs_v2_docs_prd_device_manager, llm_gateway_docs_v2_docs_prd_pinned_model, llm_gateway_docs_v2_docs_prd_runtime_events, llm_gateway_docs_v2_docs_prd_no_cpu_inference, llm_gateway_docs_v2_docs_prd_models_table [EXTRACTED 1.00]
- **Mandatory local models (Qwen2.5-7B, SD v1.5, Qwen2.5-Coder 7B/1.5B, Qwen2-VL-2B)** — llm_gateway_docs_v2_docs_prd_qwen2_5_7b, llm_gateway_docs_v2_docs_prd_sd_1_5, llm_gateway_docs_v2_docs_prd_qwen2_5_coder_7b, llm_gateway_docs_v2_docs_prd_qwen2_5_coder_1_5b, llm_gateway_docs_v2_docs_prd_qwen2_vl_2b [EXTRACTED 1.00]
- **Request admission and execution pipeline (rate limit -> quota -> resolve -> usage.start -> execute -> usage.finish)** — llm_gateway_docs_v2_tasks_task_14_public_api_v1_chat_controller, llm_gateway_docs_v2_tasks_task_16_ratelimit_quota_ratelimit_service, llm_gateway_docs_v2_tasks_task_16_ratelimit_quota_quota_service, llm_gateway_docs_v2_tasks_task_13_routing_fallback_router_service, llm_gateway_docs_v2_tasks_task_15_usage_accounting_usage_service, llm_gateway_docs_v2_tasks_task_13_routing_fallback_chat_service [EXTRACTED 1.00]
- **M3 Local Runtime milestone tasks** — llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition, llm_gateway_docs_v2_tasks_task_10_local_runtime_device_manager, llm_gateway_docs_v2_tasks_task_11_runtime_backend_openvino_llm, llm_gateway_docs_v2_tasks_task_12_runtime_backend_openvino [EXTRACTED 1.00]
- **Traefik edge protection (allowlist, rate limit, no runtime route)** — llm_gateway_docs_v2_tasks_task_22_deployment_with_traefik_traefik, llm_gateway_docs_v2_tasks_task_22_deployment_with_traefik_admin_allowlist, llm_gateway_docs_v2_tasks_task_22_deployment_with_traefik_global_ratelimit, llm_gateway_docs_v2_tasks_task_22_deployment_with_traefik_dynamic_yml [EXTRACTED 1.00]
- **Mode B network exposure security controls** — docs_deployment_mode_b_traefik, docs_deployment_behind_proxy, docs_deployment_tls_self_signed, docs_client_integration_coding_assistants [INFERRED 0.75]
- **Local models constrained by shared UMA GPU/NPU memory** — docs_hardware_uma_memory_budget, docs_model_catalog_qwen2_5_7b, docs_model_catalog_qwen2_5_coder_7b, docs_model_catalog_qwen2_5_coder_1_5b, docs_model_catalog_qwen2_vl_2b, docs_model_catalog_sd_1_5, docs_model_catalog_operational_profiles [INFERRED 0.85]
- **NF9 no-CPU-inference enforcement across accounting, metrics, admin and tests** — llm_gateway_docs_v2_tasks_task_15_usage_accounting_device_accountability, llm_gateway_docs_v2_tasks_task_18_health_metrics_cpu_device_alarm, llm_gateway_docs_v2_tasks_task_17_admin_api_audit_pinned_vram_budget, llm_gateway_docs_v2_tasks_task_20_testing_qa_hardware_tests [INFERRED 0.85]
- **OpenRouter request lifecycle: auth, chat completions, streaming, errors** — openrouter_bearer_api_key_auth, openrouter_chat_completions_api, openrouter_sse_streaming, openrouter_error_codes [INFERRED 0.85]
- **Request recording & usage accounting pipeline** — docs_database_requests, docs_database_request_attempts, docs_database_usage_daily, docs_operations_usage_fallback_replay, docs_operations_orphan_sweeper, docs_database_usage_consistency_check [INFERRED 0.85]
- **Provider adapters implementing BaseProvider contract** — llm_gateway_docs_v2_tasks_task_06_provider_base_registry_streaming_baseprovider, llm_gateway_docs_v2_tasks_task_07_provider_openai_openaiprovider, llm_gateway_docs_v2_tasks_task_08_provider_anthropic_gemini_anthropicprovider, llm_gateway_docs_v2_tasks_task_08_provider_anthropic_gemini_geminiprovider, llm_gateway_docs_v2_tasks_task_10_local_runtime_device_manager_localruntimeprovider [INFERRED 0.95]
- **OpenVINO runtime backends implementing LocalBackend** — llm_gateway_docs_v2_tasks_task_10_local_runtime_device_manager_localbackend, llm_gateway_docs_v2_tasks_task_11_runtime_backend_openvino_llm_ov_llm_backend, llm_gateway_docs_v2_tasks_task_11_runtime_backend_openvino_llm_ov_vlm_backend, llm_gateway_docs_v2_tasks_task_12_runtime_backend_openvino_ov_diffusion_backend [INFERRED 0.95]

## Communities (161 total, 37 thin omitted)

### Community 0 - "Model & Project Services"
Cohesion: 0.06
Nodes (74): ProjectAllowedModel, ApiKeyCreatedOut, ApiKeyOut, ModelOut, _Out, ProjectOut, ProviderOut, QuotaOut (+66 more)

### Community 1 - "Chat/Image Service Context"
Cohesion: 0.07
Nodes (34): create_embeddings(), ModelConfig, embedding_vector(), UnifiedChatRequest, absorb_chunk(), ChatService, clamp_max_tokens(), stream_with_fallback() (+26 more)

### Community 2 - "Rate Limit & Quota"
Cohesion: 0.06
Nodes (30): period_start(), QuotaRule, QuotaService, seconds_to_reset(), Totals, _UsageEntry, _Bucket, Decision (+22 more)

### Community 3 - "Admin Catalog CRUD"
Cohesion: 0.08
Nodes (44): create_model(), create_provider(), create_route(), delete_model(), delete_provider(), delete_route(), get_catalog(), list_models() (+36 more)

### Community 4 - "database.py"
Cohesion: 0.08
Nodes (17): Settings, configure_db(), create_engine(), dispose_db(), get_engine(), init_db(), ping_db(), _cleanup_ratelimit_forever() (+9 more)

### Community 5 - "Provider Base & Registry"
Cohesion: 0.06
Nodes (18): ProviderHealth, UnifiedChatResponse, AnthropicProvider, _message(), drop_none(), GeminiProvider, _json(), LocalRuntimeProvider (+10 more)

### Community 6 - "SSE Streaming"
Cohesion: 0.08
Nodes (36): aiter_sse(), _DisconnectAware, drain_finishers(), guarded_stream(), parse_sse_lines(), _run_on_finish(), sse_event(), SSEEvent (+28 more)

### Community 7 - "Router Service & Fallback"
Cohesion: 0.10
Nodes (40): ModelCatalog, RouteConfig, RouteTarget, AllCandidatesFailed, _allowed(), Capabilities, CircuitBreaker, Router (+32 more)

### Community 8 - "OVLLMBackend"
Cohesion: 0.26
Nodes (3): OVLLMBackend, chunk(), events_to_chunks()

### Community 9 - "Usage Accounting"
Cohesion: 0.06
Nodes (24): _clip(), _looks_base64(), strip_images(), _upsert_daily(), UsageService, _on_finish(), _utc_day(), write_record() (+16 more)

### Community 10 - "Public API Controllers"
Cohesion: 0.15
Nodes (5): completions(), embeddings(), EmbeddingRequest, require_admin(), require_scope()

### Community 11 - "Device Manager"
Cohesion: 0.07
Nodes (12): ModelBusy, LocalModelSpec, DeviceManager, DeviceStatus, EventRecorder, LoadedModel, _NullRecorder, _Events (+4 more)

### Community 12 - "Admin Keys & Schemas"
Cohesion: 0.09
Nodes (24): create_key(), list_keys(), revoke_key(), rotate_key(), set_key_allowed_models(), archive_project(), create_project(), get_project() (+16 more)

### Community 13 - "Runtime App State"
Cohesion: 0.12
Nodes (25): get_settings(), RuntimeCatalog, build_state(), create_runtime_app(), _client(), _Events, _local_provider(), _model() (+17 more)

### Community 14 - "converters.py"
Cohesion: 0.08
Nodes (34): create_chat_completion(), admit_and_start(), estimate_request_tokens(), finish_error(), get_router(), _has_payload(), open_sse(), body() (+26 more)

### Community 15 - "fake_genai.py"
Cohesion: 0.11
Nodes (9): ChatHistory, CppStdGenerator, _EmbedConfig, _encode_ids(), module(), _PoolingType, StreamerBase, StreamingStatus (+1 more)

### Community 16 - "UnifiedChunk"
Cohesion: 0.11
Nodes (10): UnifiedChunk, UnifiedCompletionRequest, UnifiedCompletionResponse, UnifiedEmbeddingResponse, UnifiedImage, Usage, BaseProvider, StreamTranslator (+2 more)

### Community 17 - "Provider Adapter Tests"
Cohesion: 0.09
Nodes (35): build_request(), sse_response(), multi_turn_request(), _collect_tool_calls(), _provider(), _req(), test_base64_and_url_images(), test_embeddings_not_supported() (+27 more)

### Community 18 - "Traefik Dynamic Config"
Cohesion: 0.04
Nodes (46): ipAllowList, buffering, maxRequestBodyBytes, memRequestBodyBytes, Server, entryPoints, rule, service (+38 more)

### Community 19 - "ORM Models Base"
Cohesion: 0.21
Nodes (14): Base, check_in(), CreatedAtMixin, TimestampMixin, uuid_pk(), Model, Project, Provider (+6 more)

### Community 20 - "Tool Call Parsers"
Cohesion: 0.10
Nodes (23): _could_be_lenient_call(), parse_hermes(), parse_lenient(), parse_tool_output(), ParsedOutput, _partial_suffix(), StreamToolParser, _to_openai() (+15 more)

### Community 21 - "Gemini/Anthropic Message Mapping"
Cohesion: 0.16
Nodes (17): dumps_arguments(), loads_arguments(), parse_image_url(), ParsedImage, build_contents(), clean_schema(), _function_response(), map_finish() (+9 more)

### Community 22 - "Admin Projects & Observe"
Cohesion: 0.29
Nodes (17): actor(), archive_project(), create_key(), create_project(), get_project(), list_keys(), list_projects(), list_quotas() (+9 more)

### Community 23 - "Retention Maintenance"
Cohesion: 0.10
Nodes (14): GeneratedImage, RequestPayload, RuntimeEvent, MaintenanceService, seconds_until_daily_run(), utcnow(), _bulk_requests(), _count() (+6 more)

### Community 24 - "test_health_ready.py"
Cohesion: 0.07
Nodes (23): adapter_of(), keyless(), ProviderRegistry, ProviderConfig, check_db(), HealthService, render(), _admin_key() (+15 more)

### Community 25 - "Logger & Redaction"
Cohesion: 0.11
Nodes (12): _attach(), _console_formatter(), _file_handler(), _InProcessQueueHandler, _is_sensitive_key(), _json_formatter(), _LoggingState, _orjson_dumps() (+4 more)

### Community 26 - "Model Download & Measure Scripts"
Cohesion: 0.11
Nodes (18): DeviceMemory, main(), measure_llm(), pipeline_properties(), _prompt_of(), round_vram(), validate_budget(), local_models() (+10 more)

### Community 27 - "Traefik Static Config"
Cohesion: 0.05
Nodes (36): accessLog, bufferingSize, fields, filePath, format, api, dashboard, address (+28 more)

### Community 28 - "manage.py CLI"
Cohesion: 0.12
Nodes (27): AuditLog, clear_ov_cache(), _apply_profile(), _audit_change(), build_parser(), cmd_allow_models(), cmd_apply_profile(), cmd_clear_ov_cache() (+19 more)

### Community 29 - "Metrics & Runtime Health"
Cohesion: 0.10
Nodes (12): health_ready(), load_model(), metrics(), reload_catalog(), shutdown(), _state(), status(), unload_model() (+4 more)

### Community 30 - "OpenAI Provider"
Cohesion: 0.12
Nodes (10): valid_provider_key_env(), OpenAIProvider, parse_usage(), _upstream_message(), _cfg(), _registry(), test_adapter_chosen_per_provider(), test_custom_key_read_from_dotenv_and_static_headers() (+2 more)

### Community 31 - "PRD Concepts"
Cohesion: 0.09
Nodes (26): Additional llama.cpp models (Llama-3.2-3B, Llama-3.1-8B, Phi-3.5-mini, DeepSeek-R1-Distill-Qwen-7B, nomic-embed), Admin API & runtime admin endpoints, bge-m3 OpenVINO embedding (NPU, pinned), PostgreSQL schema (projects, api_keys, providers, models, requests, usage_daily, audit_logs), FIM (Fill-in-the-Middle) autocomplete, generated_images table, Image generation /v1/images/generations (SD v1.5), llama-cpp-python (GGUF on GPU) (+18 more)

### Community 32 - "Console Env Status"
Cohesion: 0.11
Nodes (16): _dotenv(), env_status(), env_vars(), provider_key_states(), _secret(), secret_state(), _var(), _client() (+8 more)

### Community 33 - "OpenVINO Common Loading"
Cohesion: 0.15
Nodes (12): ModelLoadFailed, backend_class(), create_backend(), cache_dir(), cache_entries(), device_kind(), genai(), model_path() (+4 more)

### Community 34 - "Tasks: Local Runtime & DB"
Cohesion: 0.08
Nodes (31): Local model errors (ModelBusy, DeviceOOM, DeviceUnavailable), Alembic migrations (0001_initial), CHECK constraint ck_local_has_backend, scripts/manage.py seed (--update-local), ORM models (app/models/*: Project, ApiKey, Model, Request, GeneratedImage, RuntimeEvent...), scripts/seed_models.yaml (local model catalog & routes), manage.py CLI (create-admin-key, create-project, create-key), ModelCatalog / ModelConfig / RouteConfig (in-memory cache, reload()) (+23 more)

### Community 35 - "Image Controller"
Cohesion: 0.09
Nodes (8): create_image(), edit_image(), image_file(), images_edits(), images_generations(), ImageEditRequest, ImageGenerationRequest, OpenAIRequest

### Community 36 - "Provider Billing"
Cohesion: 0.12
Nodes (14): parse_request_tags(), BillingError, _error_message(), _failed(), fetch_anthropic(), fetch_openai(), _get_pages(), provider_billing() (+6 more)

### Community 37 - "OpenRouter Free Models"
Cohesion: 0.16
Nodes (31): OpenRouter Dots Studio Free Model Guide, Dots Studio: Dots3-Note Preview (free) (dots-studio/dots-3-note-preview), OpenRouter Google Gemma Free Models Guide, Google: Gemma 4 26B A4B (free) (google/gemma-4-26b-a4b-it), Google: Gemma 4 31B (free) (google/gemma-4-31b-it), OpenRouter LiquidAI Free Model Guide, LiquidAI: LFM2.5-2.6B (free) (liquid/lfm-2.5-2.6b), OpenRouter Cohere North Mini Code Free Model Guide (+23 more)

### Community 38 - "Hardware E2E Tests"
Cohesion: 0.11
Nodes (21): LGW-V1-03 — Profil `remote-embed-gpu`, whitelist, route, key, local(), active(), call_model(), call_retry_busy(), gw(), metric_sum(), metrics() (+13 more)

### Community 39 - "Admin Console JS"
Cohesion: 0.15
Nodes (29): actualSection(), archiveProject(), boot(), catalogItems(), createKey(), createProject(), editKeyModels(), editModels() (+21 more)

### Community 40 - "Image Input Handling"
Cohesion: 0.14
Nodes (14): PayloadTooLarge, _check_host(), _decode_data_url(), decode_image(), fetch_url(), _is_public(), load_image(), dns() (+6 more)

### Community 41 - "API Key Service"
Cohesion: 0.14
Nodes (6): ApiKey, _CachedKey, KeyService, AuthenticationError, ProjectSuspended, test_client_key_requires_project()

### Community 42 - "test_ov_embed.py"
Cohesion: 0.10
Nodes (22): InputTooLong, EmbedPlan, OVEmbedBackend, embed_spec(), fake(), _loaded(), test_batches_limited_by_padded_tokens_keep_order(), test_cpu_device_rejected_without_fallback() (+14 more)

### Community 43 - "OV LLM Tests"
Cohesion: 0.18
Nodes (24): UnsupportedParameter, _chat(), _collect(), _data_url(), fake(), _last_call(), make(), test_chat_response_and_usage() (+16 more)

### Community 44 - "Device Manager Tests"
Cohesion: 0.17
Nodes (20): spec(), Clock, Events, _manager(), test_backend_unavailable_records_load_failed(), no_backend(), test_busy_model_not_evicted_waits_then_model_busy(), test_concurrent_requests_load_once() (+12 more)

### Community 45 - "OpenVINO Model Conversion"
Cohesion: 0.12
Nodes (18): fetch_source(), _isolated_deps(), main(), main(), plan(), download_file(), download_repo(), file_url() (+10 more)

### Community 46 - "Tasks: Routing & QA"
Cohesion: 0.11
Nodes (15): Capabilities Filter (tools/vision/json/stream/fim/type), project_allowed_models glob permission, Retryable runtime errors (model_busy, device_oom, device_unavailable), router_service.resolve, /v1/completions with suffix (FIM), TASK-20 Testing, QA & Load Test, Local benchmark NF11 (bench_local.py), scripts/check.bat (ruff, mypy, coverage) (+7 more)

### Community 47 - "API v1 Integration Tests"
Cohesion: 0.13
Nodes (19): _request_rows(), test_chat_non_stream_shape_headers_and_log(), test_chat_stream_done_and_include_usage(), test_embeddings_base64_decodable_by_sdk(), test_fallback_recorded_and_all_failed_502(), test_fim_completion_autocomplete(), test_image_edits_multipart_image_to_image(), test_image_url_access_scoped_to_project() (+11 more)

### Community 48 - "Framework Examples & Backup"
Cohesion: 0.16
Nodes (8): _conn(), _counts(), main(), _run(), main(), _token_from_env(), main(), port_open()

### Community 49 - "Tasks: Setup & Core"
Cohesion: 0.12
Nodes (25): API key auth (lgw_ prefix, HMAC-SHA256 with pepper, scopes), TASK-01 Setup Environment & Project Skeleton, Conda env llm-genai (Python 3.10-3.12), create_app() FastAPI app factory (app/main.py), scripts/env.bat, MVC project structure (app/ gateway + runtime/ Local Runtime), scripts/start-gateway.bat, TASK-02 Core: Config, Error Hierarchy, App Factory (+17 more)

### Community 50 - "Profile: full"
Cohesion: 0.07
Nodes (26): is_enabled, is_pinned, is_enabled, is_pinned, is_enabled, is_pinned, is_enabled, is_pinned (+18 more)

### Community 51 - "Tasks: Usage & API v1"
Cohesion: 0.08
Nodes (24): RequestCtx / Attempt / Outcome, chat_service execute / execute_stream, First Token Timeout (60s remote / 120s local), Caller tracing (X-Caller-Task, X-Caller-Agent, metadata), chat_controller.create_chat_completion, converters to_unified / from_unified, Gateway response headers (X-Gateway-Provider/Model/Device/Attempts), Decimal Cost Formula (+16 more)

### Community 52 - "Seed Models: Models"
Cohesion: 0.08
Nodes (25): models, alias, artifact_path, artifact_sha256, context_window, convert, device, embedding_dimensions (+17 more)

### Community 53 - "Error Handling Tests"
Cohesion: 0.15
Nodes (18): _app(), _mnf(), _Body, _client(), test_body_over_limit_by_content_length_is_413(), test_body_over_limit_chunked_is_413(), gen(), test_body_under_limit_passes() (+10 more)

### Community 54 - "OV Diffusion Backend"
Cohesion: 0.15
Nodes (4): _decode_b64(), _int(), OVDiffusionBackend, _Params

### Community 56 - "Profile: ram16"
Cohesion: 0.08
Nodes (23): is_enabled, is_enabled, is_pinned, is_enabled, is_enabled, is_pinned, is_enabled, models (+15 more)

### Community 57 - "config.py"
Cohesion: 0.08
Nodes (19): ConfigError, load_settings(), runtime_bind_host(), main(), main(), _db_reachable(), _dispose_engine(), migrated_db() (+11 more)

### Community 58 - "OV Diffusion Tests"
Cohesion: 0.13
Nodes (19): sha256_artifact(), sha256_file(), _Events, fake(), _loaded(), _png(), sd_spec(), make() (+11 more)

### Community 59 - "OpenAI SDK Examples"
Cohesion: 0.12
Nodes (8): images(), json_mode(), tools(), vision(), _client(), test_chat_stream_completions_models_images(), test_errors_map_to_sdk_exceptions(), serve()

### Community 60 - "Profile: remote-only"
Cohesion: 0.08
Nodes (23): is_enabled, is_enabled, is_enabled, is_enabled, is_enabled, is_enabled, models, local/qwen2.5-7b (+15 more)

### Community 61 - "Load Tests & Port Wait"
Cohesion: 0.16
Nodes (10): main(), wait_port(), _duration(), fake_gateway(), _free_port(), _open_loop(), _pct(), _save() (+2 more)

### Community 62 - "Admin Integration Tests"
Cohesion: 0.13
Nodes (11): admin(), _audit_count(), _audits(), _project_id(), test_catalog_pricing_and_provider_auto_route(), test_key_allowed_models_override_project(), test_model_route_changes_apply_without_restart(), test_pin_over_budget_rejected_atomically() (+3 more)

### Community 63 - "Auth Integration Tests"
Cohesion: 0.13
Nodes (29): get_logger(), setup_logging(), shutdown_logging(), _app(), _bearer(), _chat(), client(), _key() (+21 more)

### Community 64 - "Hardware LLM Tests"
Cohesion: 0.16
Nodes (12): catalog_spec(), spec_for(), gpu(), _call(), managers(), test_cancel_mid_stream_then_serves_next(), test_chat_stream_and_usage(), test_fim_on_npu_ttft() (+4 more)

### Community 65 - "spike_embed.py"
Cohesion: 0.12
Nodes (19): eval_set(), _long_text(), _long_texts(), query_set(), categories(), _dir_mb(), GenAIEmbedder, l2() (+11 more)

### Community 66 - "Task list - LLM Gateway (PRD v2.0)"
Cohesion: 0.11
Nodes (27): Deployment modes (without/with Traefik), Rate limit (in-memory RPM/TPM) & quotas, Task list - LLM Gateway (PRD v2.0), TASK-13 Router & fallback, TASK-14 Public API v1, POST /v1/images/edits (image-to-image), openai_compat schemas (ChatCompletionRequest etc.), TASK-15 Usage, Cost Accounting & Request Log (+19 more)

### Community 67 - "Seed Models: Local Params"
Cohesion: 0.08
Nodes (26): allowed_sizes, cache_dir, cached_input_cost_per_mtok, default_steps, default_strength, device, drop_params, fim_max_prompt_tokens (+18 more)

### Community 68 - "DB Model Tests"
Cohesion: 0.19
Nodes (14): _count(), _load_manage(), _make_chain(), _seed_data(), test_check_constraints(), test_delete_project_cascades_keys_and_nulls_requests(), test_delete_request_cascades(), test_insert_chain_and_defaults() (+6 more)

### Community 69 - "Tasks: Errors & Providers"
Cohesion: 0.18
Nodes (21): CapabilityNotSupported, error_handler middleware, GatewayError hierarchy (app/utils/errors.py), UpstreamError family (UpstreamTimeout, UpstreamRateLimited, UpstreamBadRequest), TASK-06 Provider Abstraction, Registry & Streaming, aiter_sse upstream SSE parser, BaseProvider ABC (app/services/providers/base.py), Fake provider (tests/fakes/fake_provider.py) (+13 more)

### Community 70 - "unified.py"
Cohesion: 0.14
Nodes (22): FunctionCall, FunctionDef, ImagePart, ImageURL, _Model, RuntimeMeta, TextPart, ToolCall (+14 more)

### Community 71 - "Model Memory Measurement"
Cohesion: 0.20
Nodes (8): put(), worker(), PeakSampler, main(), _png(), run(), generate(), _to_tensor()

### Community 72 - "App Factory & Test Setup"
Cohesion: 0.19
Nodes (7): api(), Api, build_fake_gateway(), factory(), default_project_keys(), _project_key(), test_query_prefix_priority_and_legacy_client()

### Community 73 - "OpenAI Provider Tests"
Cohesion: 0.23
Nodes (17): model_cfg(), provider_cfg(), sse_body(), _provider(), _req(), _status(), test_bad_request_forwards_upstream_message(), test_chat_payload_has_no_none_fields_and_maps_response() (+9 more)

### Community 74 - "Admin Query Pagination"
Cohesion: 0.24
Nodes (12): decode_cursor(), encode_cursor(), get_request(), _jsonable(), _limit(), list_audit(), list_requests(), list_runtime_events() (+4 more)

### Community 75 - "Inference Service"
Cohesion: 0.17
Nodes (7): DeviceUnavailable, ModelNotWhitelisted, observe_generation(), Lease, InferenceService, _with_warnings(), x_runtime()

### Community 76 - "helper.py"
Cohesion: 0.11
Nodes (15): live(), metrics(), _privileged(), ready(), live(), metrics(), ready(), _dependency() (+7 more)

### Community 77 - "model_controller.py"
Cohesion: 0.22
Nodes (10): _allowed(), get_model(), list_models(), _objects(), get_model(), list_models(), _capabilities(), model_object() (+2 more)

### Community 78 - "API Key Crypto"
Cohesion: 0.21
Nodes (10): generate_api_key(), hash_api_key(), parse_key_prefix(), _pepper(), verify(), test_generate_format_and_hash(), test_hash_depends_on_pepper(), test_keys_are_unique() (+2 more)

### Community 79 - "asyncio"
Cohesion: 0.07
Nodes (12): CapabilityNotSupported, embedding_response(), ImageResult, iterate_in_thread(), LoadResult, LocalBackend, cancel_bridge(), _generate() (+4 more)

### Community 80 - "Request Context Middleware"
Cohesion: 0.11
Nodes (5): _header(), _incoming_request_id(), RequestContextMiddleware, require_runtime_token(), live()

### Community 81 - "Client Integration Docs"
Cohesion: 0.15
Nodes (16): API key lgw_<prefix>_<secret> (HMAC + pepper), X-Caller-Task / X-Caller-Agent headers, X-Gateway-Model / Provider / Device response headers, api_keys table, Database ERD (PostgreSQL llm_gateway), generated_images table, projects table, quotas table (+8 more)

### Community 82 - "runtime/core/lifespan.py"
Cohesion: 0.08
Nodes (13): check_devices(), lifespan(), RuntimeStartError, detect(), DeviceProbe, _probe_openvino(), _probe_system(), _as_uuid() (+5 more)

### Community 83 - "Local Benchmarks"
Cohesion: 0.26
Nodes (10): bench_chat(), bench_fim(), bench_image(), load_ms(), main(), pct(), png_data_url(), render() (+2 more)

### Community 84 - "Alembic Migrations"
Cohesion: 0.12
Nodes (12): downgrade(), upgrade(), downgrade(), _in(), upgrade(), downgrade(), _in(), upgrade() (+4 more)

### Community 85 - "Error Handler Middleware"
Cohesion: 0.13
Nodes (11): BodySizeLimitMiddleware, limited_receive(), _drain_receive(), gateway_error_response(), _handle_gateway_error(), _handle_http_exception(), _handle_unexpected(), _handle_validation_error() (+3 more)

### Community 86 - "test_runtime_embed.py"
Cohesion: 0.16
Nodes (19): DeviceInfo, _app(), _client(), _close(), _Events, _factory(), _provider(), specs() (+11 more)

### Community 87 - "Admin Usage Verification"
Cohesion: 0.22
Nodes (5): verify_usage(), provider_billing(), usage(), usage_by_tag(), usage_verify()

### Community 88 - "Profile Integration Tests"
Cohesion: 0.28
Nodes (11): load_seed(), _manage(), _profile(), routes_of(), _state(), test_apply_ram16_then_full_roundtrip(), test_full_profile_matches_seed_routes(), test_invalid_profile_rejected_without_changes() (+3 more)

### Community 89 - "bench_embed.py"
Cohesion: 0.14
Nodes (11): catalog_spec(), kb_chunks(), latency(), main(), make_chunks(), PeakMemory, quality(), recall() (+3 more)

### Community 90 - "models"
Cohesion: 0.08
Nodes (25): is_enabled, is_enabled, is_enabled, is_enabled, is_enabled, is_pinned, is_enabled, models (+17 more)

### Community 91 - "Release & DB Decisions"
Cohesion: 0.22
Nodes (9): Release 0.1.0 (2026-10-28), audit_logs table, models table (runtime catalog source of truth), providers table, runtime_events table, Operational profiles (remote-only, ram16, full), Custom provider adapters (openai / anthropic / gemini), Load test results (fake provider, 1 worker) (+1 more)

### Community 92 - "NPU & FIM Model Notes"
Cohesion: 0.22
Nodes (10): Continue Qwen FIM prompt template, Default virtual routes (fast, smart, local, code, autocomplete, vision, image, embed-default), local/qwen2.5-7b, local/qwen2.5-coder-1.5b (NPU, FIM), local/qwen2.5-coder-7b, local/qwen2-vl-2b (vision), Remote model seed (Claude Sonnet/Haiku, GPT-5, Gemini Flash, embeddings), local/sd-1.5 (Stable Diffusion v1.5, NPU) (+2 more)

### Community 93 - "Deployment Mode A & Device Budget"
Cohesion: 0.25
Nodes (11): Deployment Mode A (no Traefik), Runtime supervisor (start-runtime.bat, max 5 restarts), Orphan sweeper (pending -> error after 10 min), PRD - LLM Gateway v2.0, llm_gateway (OpenAI-compatible LLM gateway), Local Runtime (127.0.0.1:8100), Gateway endpoints (/v1, /admin, /health, /metrics), start-all.bat / stop-all.bat (+3 more)

### Community 94 - "Local Smoke Script"
Cohesion: 0.45
Nodes (10): _chat_prompt(), code_chat(), _config(), _device(), fim(), _generate(), main(), _pipe() (+2 more)

### Community 95 - "test_priority.py"
Cohesion: 0.14
Nodes (9): RequestCancelled, PrioritySemaphore, _body(), service(), test_bulk_concurrency_limited(), test_cancelled_waiter_does_not_leak_slot(), test_interactive_overtakes_running_bulk(), test_invalid_priority_and_cancel() (+1 more)

### Community 96 - "Seed Models: Providers"
Cohesion: 0.17
Nodes (12): adapter, headers, X-Title, providers, api_key_env, base_url, code, config (+4 more)

### Community 97 - "Client & Proxy Docs"
Cohesion: 0.22
Nodes (6): --behind-proxy (proxy_headers, TRUST_PROXY), Deployment Mode B (Traefik :8080, admin ipAllowList, rate limit), Optional self-signed TLS (websecure entrypoint), Device probe (Core Ultra 5 225, Intel iGPU, NPU AI Boost), Troubleshooting table (GPU load failure = system RAM exhausted), Pending Traefik Mode B tests

### Community 99 - "image_service.py"
Cohesion: 0.17
Nodes (7): UnifiedImageRequest, UnifiedImageResponse, ImageService, storage_root(), validate_image_params(), ImageNotFound, UnsupportedSize

### Community 100 - "Secret Scan Script"
Cohesion: 0.38
Nodes (7): _is_log(), main(), mask(), scan_db(), scan_logs(), scan_text(), _sync_url()

### Community 101 - "observe.py"
Cohesion: 0.11
Nodes (16): audit_logs(), cache_reload(), get_request(), list_requests(), provider_billing(), runtime_events(), _secret(), swap_stats() (+8 more)

### Community 102 - "Admin Runtime Routes"
Cohesion: 0.53
Nodes (3): runtime_events(), runtime_status(), swap_stats()

### Community 103 - "Console Route"
Cohesion: 0.44
Nodes (5): console_asset(), console_page(), _forbidden(), _hostname(), is_local_request()

### Community 104 - "Migrations Env"
Cohesion: 0.31
Nodes (5): _configure(), _database_url(), do_run_migrations(), run_async_migrations(), run_migrations_offline()

### Community 105 - "JS SDK Example"
Cohesion: 0.25
Nodes (7): client, dependencies, openai@^6.0.0, name, private, type, openai

### Community 106 - "providers/conftest.py"
Cohesion: 0.17
Nodes (12): json_response(), mock_http(), make(), Recorder, settings(), _bucket(), test_anthropic_converts_cents_and_counts_cache_tokens(), handler() (+4 more)

### Community 108 - "Admin API (/admin endpoints)"
Cohesion: 0.13
Nodes (14): GET /v1/images/files/{image_id}, image_controller / image_service, generated_images table, runtime_events table, Admin API (/admin endpoints), Cursor pagination (created_at,id), If-Match optimistic concurrency on PATCH, Runtime admin endpoints (status/load/unload/events/swap-stats) (+6 more)

### Community 109 - "Custom Provider Tests"
Cohesion: 0.25
Nodes (3): admin(), test_add_custom_provider_model_route_and_call_it(), test_secret_exfiltration_and_bad_config_rejected()

### Community 110 - "Hermes Tool Prompt"
Cohesion: 0.36
Nodes (3): _call_block(), render_hermes_messages(), tools_system_block()

### Community 111 - "Seed Models: Routes"
Cohesion: 0.29
Nodes (6): routes, alias, description, targets, model, priority

### Community 112 - "Admin Console Feature"
Cohesion: 0.33
Nodes (6): Konsol LLM Gateway page (index.html), Admin Console (/console), GET /admin/env-status, model_routes / model_route_targets tables, Per-key allowed model patterns, <provider>/auto routes

### Community 116 - "Image2ImagePipeline"
Cohesion: 0.23
Nodes (4): Image2ImagePipeline, _ImagePipeline, Tensor, Text2ImagePipeline

### Community 117 - ".stream_generate"
Cohesion: 0.24
Nodes (4): on_text(), put(), work(), write()

### Community 118 - "SD1.5 img2img Smoke"
Cohesion: 0.50
Nodes (5): SD1.5 Image-to-Image Smoke Test Output, Image-to-Image (img2img) Generation, Image Generation Smoke Test, Stable Diffusion 1.5, Surreal Painted Scene (hooded figure with ornate ring, starry blue landscape, moon)

### Community 120 - "SD1.5 txt2img Smoke"
Cohesion: 0.67
Nodes (4): SD1.5 Text-to-Image Smoke Test Output, Image Generation Smoke Test, Stable Diffusion 1.5, Text-to-Image Generation

### Community 121 - "Vision Smoke Input"
Cohesion: 0.67
Nodes (4): Text 'GATEWAY 42' (OCR target), Vision Smoke Test Input Image, Red Rectangle (color recognition target), Vision Model Smoke Test

### Community 122 - "SD Component Devices"
Cohesion: 0.50
Nodes (4): text_encoder, unet, vae, component_devices

### Community 123 - ".generate"
Cohesion: 0.25
Nodes (4): FinishReason, GenerationConfig, LLMPipeline, VLMPipeline

### Community 148 - "test_helper.py"
Cohesion: 0.24
Nodes (7): new_request_id(), _scope(), test_client_ip(), test_estimate_tokens(), test_glob_match(), test_new_request_id_is_uuid7_and_ordered(), test_utcnow_is_aware()

### Community 149 - "Task v1.0.0 — LLM Gateway (Embedding Lokal OpenVINO GPU & Dukungan Market Intelligence)"
Cohesion: 0.20
Nodes (9): Daftar Task, LGW-V1-02 — Backend runtime `openvino_embed`, LGW-V1-04 — Embedding volume besar, LGW-V1-05 — Benchmark di GPU target, LGW-V1-06 — Route `creative`/`extract`, structured output, tag usage, budget, LGW-V1-07 — Testing, dokumentasi, rilis v1.0.0, Ringkasan, Task v1.0.0 — LLM Gateway (Embedding Lokal OpenVINO GPU & Dukungan Market Intelligence) (+1 more)

### Community 150 - "TASK-09 Hardware probe, model download/convert & measure"
Cohesion: 0.24
Nodes (9): Milestones M1-M6, Critical path 01-02-04-09-10-11-13-15-14-20, TASK-09 Hardware probe, model download/convert & measure, requirements-local.txt (openvino, openvino-genai, optimum-intel, nncf pinned), TASK-10 Local Runtime + Device/VRAM Manager, TASK-11 Backend OpenVINO GenAI (Qwen text, code/FIM, vision), image_input.py (anti-SSRF image fetch & resize), ov_vlm_backend (kind=openvino_vlm, VLMPipeline) (+1 more)

### Community 152 - "test_live_providers.py"
Cohesion: 0.36
Nodes (4): client(), _require(), test_chat_non_stream_and_stream(), test_embeddings()

### Community 155 - "OpenAI-compatible client integration (base URL /v1, lgw_ key, route as model)"
Cohesion: 0.40
Nodes (5): Coding assistant integration (Continue, Cline, Aider, Open WebUI, Cursor), Error format {error: message,type,code,param} + retry table, Framework integration (LangChain, LlamaIndex, CrewAI, AutoGen), OpenAI-compatible client integration (base URL /v1, lgw_ key, route as model), request_attempts table

### Community 156 - ".mcp.json"
Cohesion: 0.40
Nodes (4): D:\Data.Fahrul\Documents\PortableDev\bin\graphify-mcp.exe, npx, chrome-devtools, graphify

### Community 160 - "embedding_instructions"
Cohesion: 0.67
Nodes (3): embedding_instructions, document, query

## Ambiguous Edges - Review These
- `llama-cpp-python (GGUF on GPU)` → `TASK-11 switch from llama-cpp-python to OpenVINO GenAI (28 Oct 2026)`  [AMBIGUOUS]
  llm_gateway_docs_v2/tasks/README.md · relation: conceptually_related_to
- `scripts/seed_models.yaml (local model catalog & routes)` → `Revision 28 Oct 2026: Qwen + SD v1.5 on OpenVINO GPU/NPU only (no llama.cpp, no CPU)`  [AMBIGUOUS]
  llm_gateway_docs_v2/tasks/TASK-09-hardware-model-acquisition.md · relation: conceptually_related_to
- `LocalBackend ABC (runtime/backends/base.py)` → `Revision 28 Oct 2026: Qwen + SD v1.5 on OpenVINO GPU/NPU only (no llama.cpp, no CPU)`  [AMBIGUOUS]
  llm_gateway_docs_v2/tasks/TASK-10-local-runtime-device-manager.md · relation: conceptually_related_to
- `Revision 28 Oct 2026: Qwen + SD v1.5 on OpenVINO GPU/NPU only (no llama.cpp, no CPU)` → `Conda env llm-genai (Python 3.10-3.12)`  [AMBIGUOUS]
  llm_gateway_docs_v2/tasks/TASK-09-hardware-model-acquisition.md · relation: conceptually_related_to

## Knowledge Gaps
- **74 isolated node(s):** `npx`, `D:\Data.Fahrul\Documents\PortableDev\bin\graphify-mcp.exe`, `llm_gateway`, `Release v1 acceptance criteria`, `Additional llama.cpp models (Llama-3.2-3B, Llama-3.1-8B, Phi-3.5-mini, DeepSeek-R1-Distill-Qwen-7B, nomic-embed)` (+69 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 997 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **37 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TASK-09 Hardware probe, model download/convert & measure` connect `TASK-09 Hardware probe, model download/convert & measure` to `Task list - LLM Gateway (PRD v2.0)`, `Tasks: Local Runtime & DB`, `Model Memory Measurement`, `Tasks: Setup & Core`, `Local Smoke Script`, `PRD Concepts`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Are the 75 inferred relationships involving `AuthContext` (e.g. with `create_model()` and `create_provider()`) actually correct?**
  _`AuthContext` has 75 INFERRED edges - model-reasoned connections that need verification._
- **What connects `npx`, `D:\Data.Fahrul\Documents\PortableDev\bin\graphify-mcp.exe`, `llm_gateway` to the rest of the system?**
  _74 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Model & Project Services` be split into smaller, more focused modules?**
  _Cohesion score 0.06131934032983508 - nodes in this community are weakly interconnected._
- **Why does `Task list - LLM Gateway (PRD v2.0)` connect `Task list - LLM Gateway (PRD v2.0)` to `Tasks: Errors & Providers`, `Tasks: Routing & QA`, `Tasks: Setup & Core`, `TASK-09 Hardware probe, model download/convert & measure`, `Deployment Mode A & Device Budget`, `PRD Concepts`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `llama-cpp-python (GGUF on GPU)` and `TASK-11 switch from llama-cpp-python to OpenVINO GenAI (28 Oct 2026)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `scripts/seed_models.yaml (local model catalog & routes)` and `Revision 28 Oct 2026: Qwen + SD v1.5 on OpenVINO GPU/NPU only (no llama.cpp, no CPU)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._