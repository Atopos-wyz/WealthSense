(() => {
  const SCENARIOS = {
    sanction_country: {
      label: "制裁/高风险地区 · RW-011（会广播）",
      body: {
        customer_id: "DEMO-SANCTION-01",
        amount: 15000,
        currency: "CNY",
        counterparty_country: "IR",
        trade_type: "import",
        extra: { scenario: "sanction_country" },
      },
    },
    pep_overseas: {
      label: "PEP 境外对手 · RW-013（会广播）",
      body: {
        customer_id: "DEMO-PEP-01",
        amount: 80000,
        currency: "CNY",
        is_pep: true,
        has_new_overseas_counterparty: true,
        extra: { scenario: "pep_overseas" },
      },
    },
    multi_rule_combo: {
      label: "双命中 RW-011+013（会广播）",
      body: {
        customer_id: "DEMO-COMBO-01",
        amount: 250000,
        currency: "CNY",
        counterparty_country: "KP",
        is_pep: true,
        has_new_overseas_counterparty: true,
        extra: { scenario: "multi_rule_combo" },
      },
    },
    gambling_pattern: {
      label: "涉赌涉诈 · RW-019（会广播）",
      body: {
        customer_id: "DEMO-GAMBLE-01",
        amount: 50000,
        currency: "CNY",
        gambling_inbound_small: true,
        gambling_outbound_large_integer: true,
        gambling_inbound_night: true,
        extra: { scenario: "gambling_pattern" },
      },
    },
    fund_aggregation: {
      label: "分散转入集中转出 · RW-004（会广播）",
      body: {
        customer_id: "DEMO-AGG-01",
        amount: 5000,
        currency: "CNY",
        distinct_in_sources_5d: 5,
        outbound_amount_5d: 200000,
        outbound_concentration: 0.85,
        extra: { scenario: "fund_aggregation" },
      },
    },
    clean_small: {
      label: "小额干净交易 · 不广播（对照）",
      body: {
        customer_id: "DEMO-CLEAN-01",
        amount: 3000,
        currency: "CNY",
        counterparty_country: "US",
        extra: { scenario: "clean_small" },
      },
    },
  };

  const els = {
    token: document.getElementById("token"),
    scenario: document.getElementById("scenario"),
    payload: document.getElementById("payload"),
    toast: document.getElementById("toast"),
    monitorOut: document.getElementById("monitorOut"),
    customerId: document.getElementById("customerId"),
    alertBody: document.getElementById("alertBody"),
    alertOut: document.getElementById("alertOut"),
    btnConfirm: document.getElementById("btnConfirm"),
    btnExclude: document.getElementById("btnExclude"),
    subState: document.getElementById("subState"),
    subCount: document.getElementById("subCount"),
    eventFeed: document.getElementById("eventFeed"),
    apiStatus: document.getElementById("apiStatus"),
    pageTitle: document.getElementById("pageTitle"),
  };

  const titles = {
    monitor: "交易监测",
    alerts: "预警台账",
    subscribe: "订阅收报",
    cs: "客服工作台",
    advisor: "投顾建议",
    ops: "操作工单",
    profile: "客户画像",
  };

  let selectedAlertId = null;
  let lastAlerts = [];
  let eventSource = null;
  let recvCount = 0;

  function setToast(msg, type) {
    if (!els.toast) return;
    els.toast.textContent = msg || "";
    els.toast.className = "toast" + (type ? " " + type : "");
  }

  function setApiStatus(text, kind) {
    if (!els.apiStatus) return;
    els.apiStatus.className = "status" + (kind ? " " + kind : "");
    els.apiStatus.innerHTML = "<b></b>" + text;
  }

  function authHeaders() {
    const token = els.token.value.trim();
    if (!token) throw new Error("请先获取 Token");
    return {
      "Content-Type": "application/json",
      Authorization: "Bearer " + token,
    };
  }

  async function api(path, options) {
    const res = await fetch(path, options || {});
    let data = null;
    try {
      data = await res.json();
    } catch (_) {}
    if (!res.ok) {
      throw new Error((data && (data.message || data.detail)) || "HTTP " + res.status);
    }
    return data;
  }

  function fillScenario(name) {
    const sc = SCENARIOS[name];
    if (!sc) return;
    els.payload.value = JSON.stringify(sc.body, null, 2);
    els.customerId.value = sc.body.customer_id || "";
  }

  function initScenarios() {
    Object.entries(SCENARIOS).forEach(([key, val]) => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = val.label;
      els.scenario.appendChild(opt);
    });
    els.scenario.value = "sanction_country";
    fillScenario("sanction_country");
  }

  function setMetrics(d) {
    const map = {
      mHit: d ? (d.hit ? "是" : "否") : "--",
      mLevel: (d && d.alert_level) || "--",
      mWo: (d && d.work_order_id) || "--",
      mRedis: d ? String(!!d.redis_published) : "--",
      mConflict: d ? String(!!d.llm_conflict) : "--",
      mId: d && d.alert_id != null ? String(d.alert_id) : "--",
    };
    Object.entries(map).forEach(([id, text]) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    });
  }

  function renderAlerts(items) {
    lastAlerts = items || [];
    if (!lastAlerts.length) {
      els.alertBody.innerHTML = "<tr><td colspan='6'>暂无数据</td></tr>";
      selectedAlertId = null;
      els.btnConfirm.disabled = true;
      els.btnExclude.disabled = true;
      return;
    }
    els.alertBody.innerHTML = lastAlerts
      .map((item) => {
        const id = item.alert_id;
        const sel = id === selectedAlertId ? " selected" : "";
        return `<tr class="clickable${sel}" data-id="${id}">
        <td>${id}</td>
        <td class="lvl-${item.alert_level || ""}">${item.alert_level ?? "-"}</td>
        <td>${item.record_type ?? "-"}</td>
        <td>${item.status ?? "-"}</td>
        <td>${item.broadcasted ? "是" : "否"}</td>
        <td>${item.work_order_id ?? "-"}</td>
      </tr>`;
      })
      .join("");
    els.alertBody.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.addEventListener("click", () => {
        selectedAlertId = Number(tr.dataset.id);
        const found = lastAlerts.find((x) => x.alert_id === selectedAlertId);
        els.alertOut.textContent = JSON.stringify(found, null, 2);
        els.btnConfirm.disabled = false;
        els.btnExclude.disabled = false;
        renderAlerts(lastAlerts);
      });
    });
  }

  function setSubUi(state) {
    els.subState.textContent = state;
    const live = state === "订阅中";
    document.getElementById("btnSubStart").disabled = live;
    document.getElementById("btnSubStop").disabled = !live;
    if (live) setApiStatus("订阅中 · event:risk_alert", "live");
    else if (state === "出错") setApiStatus("订阅异常", "err");
    else setApiStatus(state === "已断开" ? "已断开订阅" : "服务待命", state === "已断开" ? "warn" : "");
  }

  function pushEventCard(payload) {
    const empty = document.getElementById("feedEmpty");
    if (empty) empty.remove();
    recvCount += 1;
    els.subCount.textContent = String(recvCount);
    let obj = payload;
    if (typeof payload === "string") {
      try {
        obj = JSON.parse(payload);
      } catch (_) {
        obj = { raw: payload };
      }
    }
    const card = document.createElement("article");
    card.className = "event-card";
    const level = obj.alert_level || "?";
    const rules = Array.isArray(obj.trigger_rules) ? obj.trigger_rules.join(", ") : "-";
    card.innerHTML = `
      <header>
        <strong>alert_id=${obj.alert_id ?? "-"} · ${obj.work_order_id ?? "无工单"}</strong>
        <span class="lvl-${level}">${level}</span>
      </header>
      <div class="mono">rules: ${rules}</div>
      <div class="mono">conflict=${obj.llm_conflict === true} · v=${obj.schema_version || "-"}</div>
      <details><summary>展开 JSON</summary><pre>${JSON.stringify(obj, null, 2)}</pre></details>`;
    els.eventFeed.prepend(card);
  }

  function startSubscribe() {
    if (eventSource) eventSource.close();
    setSubUi("连接中…");
    eventSource = new EventSource("/api/risk/dev/subscribe-stream");
    eventSource.addEventListener("status", (ev) => {
      try {
        const d = JSON.parse(ev.data);
        setSubUi(d.state === "subscribed" ? "订阅中" : String(d.state));
      } catch (_) {
        setSubUi("订阅中");
      }
    });
    eventSource.addEventListener("risk_alert", (ev) => pushEventCard(ev.data));
    eventSource.addEventListener("error", (ev) => {
      if (!ev.data) return;
      try {
        const d = JSON.parse(ev.data);
        setToast("订阅流错误：" + (d.message || ""), "err");
      } catch (_) {}
    });
    eventSource.onerror = () => {
      if (eventSource && eventSource.readyState === EventSource.CLOSED) setSubUi("已断开");
      else setSubUi("出错");
    };
  }

  function stopSubscribe() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    setSubUi("已断开");
  }

  function showView(name) {
    document.querySelectorAll(".view").forEach((el) => {
      el.classList.toggle("active", el.id === "view-" + name);
    });
    document.querySelectorAll(".nav-item[data-view]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.view === name);
    });
    if (els.pageTitle) els.pageTitle.textContent = titles[name] || "WealthSense";
    const layout = document.getElementById("workLayout");
    const showRail = name === "monitor" || name === "subscribe" || name === "alerts";
    if (layout) layout.classList.toggle("full", !showRail);
  }

  document.getElementById("nav").addEventListener("click", (e) => {
    const btn = e.target.closest(".nav-item[data-view]");
    if (!btn || btn.disabled) return;
    showView(btn.dataset.view);
  });

  document.querySelectorAll("[data-fake-action]").forEach((btn) => {
    btn.addEventListener("click", () => setToast("概念阶段 · 演示未接通", "warn"));
  });

  document.getElementById("btnToken").addEventListener("click", async () => {
    try {
      setToast("正在获取 Token…");
      const data = await api("/api/risk/dev/token", { method: "POST" });
      const token = data?.data?.token;
      if (!token) throw new Error(data?.data?.message || "未返回 token");
      els.token.value = token;
      setToast("Token 已就绪");
      setApiStatus("已鉴权", "");
    } catch (e) {
      setToast(e.message, "err");
    }
  });

  els.scenario.addEventListener("change", () => fillScenario(els.scenario.value));
  document.getElementById("btnFill").addEventListener("click", () => {
    fillScenario(els.scenario.value);
    setToast("已重新填充场景");
  });

  document.getElementById("btnMonitor").addEventListener("click", async () => {
    try {
      let body;
      try {
        body = JSON.parse(els.payload.value);
      } catch (_) {
        throw new Error("请求体不是合法 JSON");
      }
      setToast("监测中…");
      const data = await api("/api/risk/monitor", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(body),
      });
      const d = data?.data;
      els.monitorOut.textContent = JSON.stringify(data, null, 2);
      setMetrics(d);
      if (body.customer_id) els.customerId.value = body.customer_id;
      if (d?.hit) {
        setToast(
          `命中 ${d.alert_level} · ${d.work_order_id || ""} · redis=${d.redis_published}` +
            (d.broadcasted ? " · 请看订阅收报" : "")
        );
      } else {
        setToast(`未命中 · skip_full=${d?.skip_full} · 不应产生广播`);
      }
      if (d?.redis_error) setToast("Redis 发布失败：" + d.redis_error, "warn");
    } catch (e) {
      setToast(e.message, "err");
      els.monitorOut.textContent = e.message;
    }
  });

  document.getElementById("btnList").addEventListener("click", async () => {
    try {
      const cid = els.customerId.value.trim();
      if (!cid) throw new Error("请填写 customer_id");
      const data = await api("/api/risk/alerts?customer_id=" + encodeURIComponent(cid), {
        headers: authHeaders(),
      });
      renderAlerts(data?.data || []);
      setToast(`查询到 ${(data?.data || []).length} 条`);
      showView("alerts");
    } catch (e) {
      setToast(e.message, "err");
    }
  });

  async function handle(status) {
    try {
      if (!selectedAlertId) throw new Error("请先选中一条预警");
      const data = await api(`/api/risk/alerts/${selectedAlertId}/handle`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ status }),
      });
      els.alertOut.textContent = JSON.stringify(data, null, 2);
      setToast("已处置为「" + status + "」");
      document.getElementById("btnList").click();
    } catch (e) {
      setToast(e.message, "err");
    }
  }

  els.btnConfirm.addEventListener("click", () => handle("已确认"));
  els.btnExclude.addEventListener("click", () => handle("已排除"));

  document.getElementById("btnRedis").addEventListener("click", async () => {
    try {
      const data = await api("/api/risk/dev/redis-status", { headers: authHeaders() });
      const ok = data?.data?.ping_ok;
      setApiStatus(ok ? "Redis 正常" : "Redis 异常", ok ? "" : "err");
      setToast(ok ? "Redis ping 成功" : String(data?.data?.ping_error || "ping 失败"), ok ? "" : "err");
    } catch (e) {
      setToast(e.message, "err");
      setApiStatus("检查失败", "err");
    }
  });

  document.getElementById("btnRedisCache").addEventListener("click", async () => {
    try {
      const data = await api("/api/risk/dev/cached-alerts?limit=20", {
        headers: authHeaders(),
      });
      const d = data?.data || {};
      els.monitorOut.textContent = JSON.stringify(d, null, 2);
      setToast(
        d.error
          ? "读取缓存失败：" + d.error
          : `Redis 缓存 recent=${d.count || 0}（key=${d.key || "risk:alert:recent"}）`,
        d.error ? "err" : ""
      );
      showView("monitor");
    } catch (e) {
      setToast(e.message, "err");
    }
  });

  document.getElementById("btnSubStart").addEventListener("click", startSubscribe);
  document.getElementById("btnSubStop").addEventListener("click", stopSubscribe);
  document.getElementById("btnSubClear").addEventListener("click", () => {
    recvCount = 0;
    els.subCount.textContent = "0";
    els.eventFeed.innerHTML =
      '<div class="empty" id="feedEmpty">已清空。保持订阅可继续接收新事件。</div>';
  });

  initScenarios();
  setMetrics(null);
  setSubUi("未订阅");
  setApiStatus("服务待命", "");
  showView("monitor");
})();
