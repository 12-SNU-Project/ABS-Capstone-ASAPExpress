"""Clientside Dash callback scripts."""

RUN_CREATE_CALLBACK = """
async function(nClicks, rerunClicks, productName, description, kurlyUrl, currentRunId, resultData, apiBaseUrl) {
    const dc = window.dash_clientside || dash_clientside;
    if (!nClicks && !rerunClicks) {
        return [dc.no_update, dc.no_update];
    }
    const triggered = (
        dc.callback_context &&
        dc.callback_context.triggered &&
        dc.callback_context.triggered.length
    ) ? dc.callback_context.triggered[0].prop_id : "";
    const reconstructionOnly = triggered.indexOf("btn-rerun-reconstruction.") === 0;
    if (
        !reconstructionOnly &&
        currentRunId &&
        resultData &&
        resultData.job_id === currentRunId &&
        ["queued", "running"].includes(resultData.job_status)
    ) {
        return [currentRunId, "/classification"];
    }

    const clean = function(value) {
        return (value || "").toString().trim();
    };
    const nextProductName = clean(productName);
    const nextDescription = clean(description);
    const nextKurlyUrl = clean(kurlyUrl);
    const query = nextProductName || nextDescription || nextKurlyUrl;
    const backendBaseUrl = clean(apiBaseUrl).replace(/\\/+$/, "");
    const previousFacts = (
        resultData &&
        resultData.request &&
        resultData.request.facts &&
        typeof resultData.request.facts === "object"
    ) ? resultData.request.facts : {};
    const facts = {
        product_name: nextProductName,
        description: nextDescription,
        url: nextKurlyUrl || clean(previousFacts.url),
        source_urls: (nextKurlyUrl || clean(previousFacts.url)) ? [nextKurlyUrl || clean(previousFacts.url)] : [],
        origin_country: "KR",
        intended_use: "human consumption"
    };
    const setStore = function(data) {
        if (dc.set_props) {
            dc.set_props("store-result", {data: data});
        }
    };
    const resetRunViews = function() {
        if (!dc.set_props) {
            return;
        }
        dc.set_props("document-panel-store", {data: "overview"});
        dc.set_props("input-detail-drawer-store", {data: false});
        dc.set_props("candidate-tree-drawer-store", {data: false});
        dc.set_props("classification-result-drawer-store", {data: false});
    };

    if (window.asapPipelineSse && window.asapPipelineSse.source) {
        window.asapPipelineSse.source.close();
        window.asapPipelineSse = null;
    }
    resetRunViews();

    if (reconstructionOnly) {
        const cachedIdentifier = facts.url || clean(previousFacts.product_id);
        if (!cachedIdentifier) {
            setStore({
                job_id: null,
                job_status: "failed",
                request: {query: query, facts: facts},
                error: "캐시 reconstruction에는 URL 또는 product_id가 필요합니다.",
                events: [{
                    stage: "Input_Reconstruction",
                    status: "failed",
                    message: "캐시 reconstruction에는 URL 또는 product_id가 필요합니다."
                }]
            });
            return [dc.no_update, "/classification"];
        }
        if (!backendBaseUrl) {
            setStore({
                job_id: null,
                job_status: "failed",
                request: {query: query, facts: facts},
                error: "Backend API URL이 설정되지 않았습니다.",
                events: [{
                    stage: "Input_Reconstruction",
                    status: "failed",
                    message: "Backend API URL이 설정되지 않았습니다."
                }]
            });
            return [dc.no_update, "/classification"];
        }
        if (dc.set_props) {
            dc.set_props("btn-rerun-reconstruction", {disabled: true});
        }
        setStore({
            job_id: null,
            job_status: "submitting",
            request: {query: query || cachedIdentifier, facts: facts},
            events: [{
                stage: "Input_Reconstruction",
                status: "submitting",
                message: "캐시된 OCR evidence로 LLM reconstruction만 재실행합니다."
            }]
        });
        try {
            const response = await fetch(`${backendBaseUrl}/api/reconstruction-runs`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    url: facts.url,
                    product_id: clean(previousFacts.product_id)
                })
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.message || payload.error || "reconstruction_rerun_failed");
            }
            setStore(payload);
            return [dc.no_update, "/classification"];
        } catch (error) {
            setStore({
                job_id: null,
                job_status: "failed",
                request: {query: query || cachedIdentifier, facts: facts},
                error: String(error && error.message ? error.message : error),
                events: [{
                    stage: "Input_Reconstruction",
                    status: "failed",
                    message: String(error && error.message ? error.message : error)
                }]
            });
            return [dc.no_update, "/classification"];
        } finally {
            if (dc.set_props) {
                dc.set_props("btn-rerun-reconstruction", {disabled: false});
            }
        }
    }

    if (!query) {
        setStore({
            job_id: null,
            job_status: "failed",
            request: {query: query, facts: facts},
            error: "제품명, 설명, URL 중 하나는 입력해야 합니다.",
            events: [{
                stage: "Input",
                status: "failed",
                message: "제품명, 설명, URL 중 하나는 입력해야 합니다."
            }]
        });
        return [dc.no_update, "/classification"];
    }
    if (!backendBaseUrl) {
        setStore({
            job_id: null,
            job_status: "failed",
            request: {query: query, facts: facts},
            error: "Backend API URL이 설정되지 않았습니다.",
            events: [{
                stage: "Pipeline",
                status: "failed",
                message: "Backend API URL이 설정되지 않았습니다."
            }]
        });
        return [dc.no_update, "/classification"];
    }

    if (dc.set_props) {
        dc.set_props("btn-run", {disabled: true});
    }
    setStore({
        job_id: null,
        job_status: "submitting",
        request: {query: query, facts: facts},
        events: [{
            stage: "Pipeline",
            status: "submitting",
            message: "작업 등록을 요청하고 있습니다."
        }]
    });

    try {
        const response = await fetch(`${backendBaseUrl}/api/runs`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                query: query,
                product_name: nextProductName,
                description: nextDescription,
                url: nextKurlyUrl,
                facts: facts
            })
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || payload.error || "run_create_failed");
        }

        const queuedResult = {
            job_id: payload.job_id,
            job_status: payload.status || "queued",
            request: {query: query, facts: facts},
            events: [{
                stage: "Pipeline",
                status: payload.status || "queued",
                message: payload.reused ? "기존 실행 중인 작업에 연결했습니다." : "작업이 등록되었습니다."
            }]
        };
        setStore(queuedResult);

        try {
            const snapshotUrl = new URL(payload.result_url, `${backendBaseUrl}/`).toString();
            const snapshotResponse = await fetch(snapshotUrl);
            if (snapshotResponse.ok) {
                setStore(await snapshotResponse.json());
            }
        } catch (snapshotError) {
            // queuedResult is already enough to render initial progress.
        }
        return [payload.job_id, "/classification"];
    } catch (error) {
        setStore({
            job_id: null,
            job_status: "failed",
            request: {query: query, facts: facts},
            error: String(error && error.message ? error.message : error),
            events: [{
                stage: "Pipeline",
                status: "failed",
                message: String(error && error.message ? error.message : error)
            }]
        });
        return [dc.no_update, "/classification"];
    }
}
"""


RUN_EVENT_STREAM_CALLBACK = """
function(jobId, apiBaseUrl) {
    const dc = window.dash_clientside || dash_clientside;
    const noUpdate = dc.no_update;
    const setStore = function(data) {
        if (dc.set_props) {
            dc.set_props("store-result", {data: data});
        }
    };
    const closeCurrent = function() {
        if (window.asapPipelineSse && window.asapPipelineSse.source) {
            window.asapPipelineSse.source.close();
        }
        window.asapPipelineSse = null;
    };
    const isTerminal = function(status) {
        return ["completed", "failed"].includes(status);
    };

    closeCurrent();
    if (!jobId) {
        return noUpdate;
    }
    const backendBaseUrl = (apiBaseUrl || "").toString().trim().replace(/\\/+$/, "");
    if (!backendBaseUrl) {
        setStore({
            job_id: jobId,
            job_status: "failed",
            error: "Backend API URL이 설정되지 않았습니다.",
            events: []
        });
        return noUpdate;
    }

    fetch(`${backendBaseUrl}/api/runs/${jobId}`)
        .then(function(response) {
            if (!response.ok) {
                throw new Error("run_not_found");
            }
            return response.json();
        })
        .then(function(snapshot) {
            let state = Object.assign({}, snapshot);
            setStore(state);
            if (isTerminal(state.job_status)) {
                return;
            }

            const eventStart = Array.isArray(state.events) ? state.events.length : 0;
            const source = new EventSource(`${backendBaseUrl}/api/runs/${jobId}/events?start=${eventStart}`);
            window.asapPipelineSse = {jobId: jobId, source: source};

            const pushState = function(nextState) {
                state = Object.assign({}, nextState, {job_id: jobId});
                setStore(state);
            };
            const applyPipelineEvent = function(eventPayload) {
                const events = Array.isArray(state.events) ? state.events.slice() : [];
                events.push(eventPayload);
                const partial = (
                    eventPayload.partial_result &&
                    typeof eventPayload.partial_result === "object"
                ) ? eventPayload.partial_result : {};
                const nextStatus = (
                    eventPayload.stage === "Pipeline" &&
                    isTerminal(eventPayload.status)
                ) ? eventPayload.status : "running";
                pushState(Object.assign({}, state, partial, {
                    events: events,
                    job_status: isTerminal(state.job_status) ? state.job_status : nextStatus
                }));
            };

            source.addEventListener("pipeline_event", function(event) {
                try {
                    applyPipelineEvent(JSON.parse(event.data));
                } catch (parseError) {
                    pushState(Object.assign({}, state, {
                        job_status: "failed",
                        error: String(parseError)
                    }));
                }
            });

            source.addEventListener("run_complete", function(event) {
                let payload = {};
                try {
                    payload = JSON.parse(event.data || "{}");
                } catch (parseError) {
                    payload = {};
                }
                source.close();
                fetch(`${backendBaseUrl}/api/runs/${jobId}`)
                    .then(function(response) {
                        return response.ok ? response.json() : null;
                    })
                    .then(function(finalSnapshot) {
                        pushState(finalSnapshot || Object.assign({}, state, {
                            job_status: payload.status || state.job_status || "completed"
                        }));
                    })
                    .catch(function() {
                        pushState(Object.assign({}, state, {
                            job_status: payload.status || state.job_status || "completed"
                        }));
                    });
            });

            source.addEventListener("error", function(event) {
                if (event && event.data) {
                    try {
                        const payload = JSON.parse(event.data);
                        pushState(Object.assign({}, state, {
                            job_status: "failed",
                            error: payload.message || "sse_error"
                        }));
                    } catch (parseError) {
                        pushState(Object.assign({}, state, {
                            job_status: "failed",
                            error: String(parseError)
                        }));
                    }
                    source.close();
                }
            });
        })
        .catch(function(error) {
            setStore({
                job_id: jobId,
                job_status: "failed",
                error: String(error && error.message ? error.message : error),
                events: [{
                    stage: "Pipeline",
                    status: "failed",
                    message: String(error && error.message ? error.message : error)
                }]
            });
        });

    return noUpdate;
}
"""
