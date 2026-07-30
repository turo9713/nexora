"use strict";

const state={csrf:null,realtime:null,realtimeWorkspace:null,realtimeCallback:null,notificationWorkspace:null,notificationRefresh:null};
const el=id=>document.getElementById(id);
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n};
const fmt=value=>value?new Date(value).toLocaleString("ru-RU",{dateStyle:"short",timeStyle:"short"}):"—";
const badge=value=>{const n=node("span",value,"badge "+String(value).toLowerCase());return n};

async function api(path,options={}){const headers={"Accept":"application/json",...(options.headers||{})};if(options.body){headers["Content-Type"]="application/json"}if(state.csrf&&options.method&&options.method!=="GET")headers["X-CSRF-Token"]=state.csrf;const response=await fetch(path,{credentials:"same-origin",...options,headers});const data=await response.json().catch(()=>({error:"INVALID_RESPONSE"}));if(response.status===401){showLogin();throw new Error("UNAUTHORIZED")}if(!response.ok)throw new Error(data.message||data.error||"Ошибка запроса");return data}
function clear(){el("content").replaceChildren()}
function card(title,wide=false){const c=node("article",undefined,"card "+(wide?"wide":""));c.append(node("h2",title));return c}
function metric(label,value){const m=node("div",undefined,"metric");m.append(node("strong",value),node("span",label));return m}
function showLogin(){el("app").classList.add("hidden");el("login").classList.remove("hidden");state.csrf=null;state.realtimeCallback=null;state.notificationWorkspace=null;closeNotificationTray();closeCommandPalette();closeQuickTask();if(state.realtime){state.realtime.close();state.realtime=null;state.realtimeWorkspace=null}}
function showApp(){el("login").classList.add("hidden");el("app").classList.remove("hidden")}
function title(value){el("page-title").textContent=value;document.title=value+" · Nexora"}
function selectMenuTab(name,remember=true){
  const panel=document.querySelector(`[data-menu-panel="${name}"]`);
  if(!panel)return;
  document.querySelectorAll("[data-menu-panel]").forEach(item=>item.classList.toggle("active",item===panel));
  document.querySelectorAll("[data-menu-tab]").forEach(button=>{
    const active=button.dataset.menuTab===name;
    button.classList.toggle("active",active);
    button.setAttribute("aria-selected",String(active));
  });
  if(remember){try{sessionStorage.setItem("nexora-menu-tab",name)}catch{}}
}
function activate(path){
  let current=null;
  document.querySelectorAll("nav a").forEach(a=>{const active=a.dataset.route===path;a.classList.toggle("active",active);if(active)current=a});
  const panel=current?.closest("[data-menu-panel]");
  if(panel)selectMenuTab(panel.dataset.menuPanel,false);
}
function errorView(error){clear();const c=card("Не удалось загрузить данные");c.classList.add("full");c.append(node("p",error.message,"danger"));el("content").append(c)}

function closeNotificationTray(){
  const tray=el("notification-tray");const toggle=el("notification-toggle");
  if(tray)tray.classList.add("hidden");
  if(toggle)toggle.setAttribute("aria-expanded","false");
}
async function refreshNotificationCenter(render=true){
  if(!state.notificationWorkspace)return;
  const data=await api(`/api/notifications?workspace_id=${encodeURIComponent(state.notificationWorkspace)}&limit=8`);
  const count=el("notification-count");count.textContent=String(data.unread||0);count.classList.toggle("hidden",!data.unread);
  el("notification-toggle").setAttribute("aria-label",data.unread?`Уведомления: ${data.unread} непрочитанных`:"Новых уведомлений нет");
  if(!render)return data;
  const items=el("notification-items");items.replaceChildren();
  (data.items||[]).forEach(item=>{
    const row=node("div",undefined,"notification-item");const info=node("div");
    info.append(node("strong",item.message),node("small",`${item.type} · ${fmt(item.created_at)}`,"muted"));row.append(info);
    if(item.status==="UNREAD"){const read=node("button","Прочитано","secondary");read.type="button";read.onclick=async event=>{event.stopPropagation();read.disabled=true;await api(`/api/notifications/${item.id}/read?workspace_id=${encodeURIComponent(state.notificationWorkspace)}`,{method:"POST",body:"{}"});await refreshNotificationCenter(true)};row.append(read)}
    items.append(row);
  });
  if(!data.items?.length)items.append(node("div","Новых уведомлений нет","empty"));
  return data;
}
async function initializeNotificationCenter(){
  const summary=await api("/api/dashboard");
  state.notificationWorkspace=summary.workspace.id;
  await refreshNotificationCenter(false);
  connectRealtime(summary.workspace.id,summary.realtime_cursor);
}
function scheduleNotificationRefresh(){
  if(state.notificationRefresh)clearTimeout(state.notificationRefresh);
  state.notificationRefresh=setTimeout(()=>refreshNotificationCenter(!el("notification-tray").classList.contains("hidden")).catch(()=>{}),250);
}
function closeQuickTask(){
  el("quick-task-modal").classList.add("hidden");
  el("quick-task-form").reset();
  el("quick-task-error").textContent="";
  el("quick-task-submit").disabled=false;
  el("quick-task-submit").textContent="Запустить агентов";
}
function openQuickTask(){
  closeNotificationTray();
  closeCommandPalette();
  el("quick-task-modal").classList.remove("hidden");
  el("quick-task-message").focus();
}
function commandEntries(){
  const routes=[...document.querySelectorAll("#nav a[data-route]")].map(link=>({
    label:link.textContent.trim(),
    path:link.getAttribute("data-route"),
    group:link.closest("[data-menu-panel]")?.dataset.menuPanel||"work"
  }));
  return [{label:"Новая задача",path:null,group:"work",action:"new-task"},...routes];
}
function renderCommandPalette(query=""){
  const normalized=query.trim().toLocaleLowerCase("ru-RU");
  const matches=commandEntries().filter(item=>!normalized||`${item.label} ${item.path||""} ${item.group}`.toLocaleLowerCase("ru-RU").includes(normalized)).slice(0,12);
  const results=el("command-results");results.replaceChildren();
  matches.forEach(item=>{
    const button=node("button",undefined,"command-item");button.type="button";button.setAttribute("role","option");
    button.append(node("strong",item.label),node("small",item.action==="new-task"?"Запустить Orchestrator":item.path,"muted"));
    button.onclick=()=>{closeCommandPalette();if(item.action==="new-task")openQuickTask();else navigate(item.path)};
    results.append(button);
  });
  if(!matches.length)results.append(node("div","Ничего не найдено","empty"));
}
function closeCommandPalette(){
  el("command-modal").classList.add("hidden");
  el("command-input").value="";
}
function openCommandPalette(){
  closeNotificationTray();closeQuickTask();renderCommandPalette();
  el("command-modal").classList.remove("hidden");
  el("command-input").focus();
}

async function dashboard(){title("Nexora Dashboard");activate("/");const data=await api("/api/health");clear();const grid=node("div",undefined,"grid");const health=card("System Health",true);[["Runtime",data.runtime],["Web Runtime",data.web_runtime],["Telegram",data.telegram],["API",data.api],["Database",data.database],["Marketplace",data.marketplace],["Agents",`${data.agents_loaded} loaded`],["Skills",`${data.skills.active}/${data.skills.loaded} active`],["Gateway",data.gateway]].forEach(([k,v])=>{const row=node("div",undefined,"health-row");row.append(node("span",k),node("strong",v,String(v).toLowerCase()==="ok"?"ok":"warning"));health.append(row)});const tasks=card("Tasks Overview");const metrics=node("div",undefined,"metrics");metrics.append(metric("Running",data.tasks.running),metric("Completed today",data.tasks.completed_today),metric("Failed",data.tasks.failed),metric("Waiting approval",data.tasks.waiting_approval));tasks.append(metrics);const agents=card("Platform",true);agents.append(node("p","API, agents, skills и integrations используют Policy Engine и одноразовые approvals.","muted"));const go=node("button","Открыть метрики","secondary");go.onclick=()=>navigate("/metrics");agents.append(go);grid.append(health,tasks,agents);el("content").append(grid)}

const TASK_STATUSES=["NEW","CLARIFYING","QUEUED","PLANNING","IN_PROGRESS","WAITING_APPROVAL","COMPLETED","FAILED","CANCELLED","EXPIRED"];
const taskStatusLabel=status=>({NEW:"⚪ NEW",CLARIFYING:"🔵 CLARIFYING",QUEUED:"🟡 QUEUED",PLANNING:"🟡 PLANNING",IN_PROGRESS:"🟡 IN_PROGRESS",WAITING_APPROVAL:"🟠 WAITING_APPROVAL",COMPLETED:"🟢 COMPLETED",FAILED:"🔴 FAILED",CANCELLED:"⚫ CANCELLED",EXPIRED:"⚫ EXPIRED"}[status]||status||"—");

async function tasksPage(){title("Task Control Center");activate("/tasks");clear();const notice=card("Задачи Nexora",true);notice.classList.add("full");notice.append(node("p","Безопасный режим просмотра: Task Control Center не запускает, не изменяет и не отменяет задачи.","muted"));const toolbar=node("form",undefined,"toolbar");const search=node("input");search.placeholder="Поиск по ID или названию";const status=node("select");["",...TASK_STATUSES].forEach(v=>{const o=node("option",v||"Все статусы");o.value=v;status.append(o)});const submit=node("button","Применить","secondary");toolbar.append(search,status,submit);const wrap=node("div",undefined,"table-wrap");el("content").append(notice,toolbar,wrap);async function load(event){if(event)event.preventDefault();const q=new URLSearchParams();if(search.value)q.set("search",search.value);if(status.value)q.set("status",status.value);const data=await api("/api/tasks?"+q);const table=node("table");const head=node("tr");["Task ID","Название","Статус","Этап","Прогресс","Агент","Workflow","Provider","Создана","Обновлена","Завершена"].forEach(x=>head.append(node("th",x)));const thead=node("thead");thead.append(head);const body=node("tbody");data.items.forEach(item=>{const row=node("tr");row.dataset.id=item.task_id;row.append(node("td",item.task_id),node("td",item.title));const statusCell=node("td");statusCell.append(badge(taskStatusLabel(item.status)));row.append(statusCell,node("td",item.stage||"—"),node("td",`${item.progress}%`),node("td",item.assigned_agent||"—"),node("td",item.workflow||"—"),node("td",item.provider_mode||"—"),node("td",fmt(item.created_at)),node("td",fmt(item.updated_at)),node("td",fmt(item.completed_at)));row.onclick=()=>navigate(`/tasks/${encodeURIComponent(item.task_id)}`);body.append(row)});table.append(thead,body);wrap.replaceChildren(data.items.length?table:node("div","Задач не найдено","empty"))}toolbar.onsubmit=load;await load()}

async function taskPage(id){title("Карточка задачи");activate("/tasks");const encoded=encodeURIComponent(id);const [item,timeline]=await Promise.all([api(`/api/tasks/${encoded}`),api(`/api/tasks/${encoded}/events`)]);clear();const c=card(`Задача ${item.task_id}`,true);c.classList.add("full");const badges=node("div",undefined,"actions");badges.append(badge(taskStatusLabel(item.status)),badge(`Агент: ${item.assigned_agent||"—"}`),badge(`Workflow: ${item.workflow||"—"}`));c.append(badges);const details=node("div",undefined,"detail-grid");[["Task ID",item.task_id],["Название",item.title],["Статус",item.status],["Этап",item.stage||"—"],["Прогресс",`${item.progress}%`],["Агент",item.assigned_agent||"—"],["Workflow",item.workflow||"—"],["Provider",item.provider_mode||"—"],["Создана",fmt(item.created_at)],["Обновлена",fmt(item.updated_at)],["Завершена",fmt(item.completed_at)],["Ошибка",item.error_code||"—"]].forEach(([k,v])=>{const d=node("div",undefined,"detail");d.append(node("small",k),node("strong",v));details.append(d)});c.append(details,node("h3","Описание"),node("p",item.description||"Описание не записано для этой задачи.","muted"),node("h3","Результат"),node("pre",item.result_summary||"Результат пока отсутствует"));const actions=node("div",undefined,"actions");if((item.downloads||[]).length){const download=node("a","Скачать безопасный результат .txt","button-link");download.href=`/api/tasks/${encoded}/downloads/result`;download.download=item.downloads[0].name;actions.append(download)}if(item.status==="WAITING_APPROVAL"){const approvals=node("a","Открыть подтверждения","button-link");approvals.href="/approvals";approvals.dataset.route="/approvals";actions.append(approvals)}if(actions.childNodes.length)c.append(actions);c.append(node("h3","Timeline"));const events=timeline.items||[];if(!events.length)c.append(node("div","Lifecycle events пока отсутствуют.","empty"));events.forEach(event=>{const row=node("div",undefined,"approval-row");const info=node("div");info.append(node("strong",event.type),node("p",[event.status,event.stage,event.agent,event.workflow].filter(Boolean).join(" · ")||"Без дополнительных данных","muted"));row.append(info,node("small",fmt(event.timestamp),"muted"));c.append(row)});el("content").append(c)}

const agentStatusLabel=status=>status==="ACTIVE"?"🟢 ACTIVE":status==="IDLE"?"⚪ IDLE":"🔴 DISABLED";

async function agentsPage(){title("Agent Control Center");activate("/agents");const data=await api("/api/agents");clear();const intro=card("Агенты Nexora",true);intro.classList.add("full");intro.append(node("p","Безопасный режим просмотра: разрешения и состояние агентов нельзя изменять из Dashboard.","muted"));const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.name);c.append(badge(agentStatusLabel(item.status)),node("p",item.description),node("p",`ID: ${item.id} · Роль: ${item.role}`,"muted"),node("p",`Риск: ${item.risk_level} · Выполнено задач: ${item.completed_tasks}`),node("p",`Последняя активность: ${fmt(item.last_activity)}`,"muted"),node("p",`Инструменты: ${item.allowed_tools.join(", ")||"нет"}`));const more=node("button","Подробнее","secondary");more.onclick=()=>navigate(`/agents/${item.id}`);c.append(more);grid.append(c)});el("content").append(intro,grid)}

async function agentPage(id){title("Карточка агента");activate("/agents");const item=await api(`/api/agents/${encodeURIComponent(id)}`);clear();const c=card(item.name,true);c.classList.add("full");const details=node("div",undefined,"detail-grid");[["Agent ID",item.id],["Статус",agentStatusLabel(item.status)],["Роль",item.role],["Риск",item.risk_level],["Выполнено задач",item.completed_tasks],["Последняя активность",fmt(item.last_activity)]].forEach(([key,value])=>{const detail=node("div",undefined,"detail");detail.append(node("small",key),node("strong",value));details.append(detail)});c.append(details,node("p",item.description),node("h3","Разрешения"),node("pre",item.permissions.join("\n")||"нет"),node("h3","Разрешённые инструменты"),node("pre",item.allowed_tools.join("\n")||"нет"),node("h3","Ограничения"),node("pre",item.restrictions.join("\n")||"нет"),node("h3","Последние задачи"));if(!item.recent_tasks.length)c.append(node("div","Задач пока нет","empty"));item.recent_tasks.forEach(task=>{const r=node("div",undefined,"agent-row");r.append(node("span",task.title),badge(task.status));c.append(r)});el("content").append(c)}

async function skillsPage(){title("Nexora Skills");activate("/skills");const data=await api("/api/skills");clear();const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.name);c.append(badge(item.status),node("p",`Version: ${item.version} · Agent: ${item.agent}`,"muted"),node("p",`Risk: ${item.risk}`),node("p",`Tools: ${item.tools.join(", ")}`));const more=node("button","Открыть manifest","secondary");more.onclick=()=>navigate(`/skills/${item.id}`);c.append(more);grid.append(c)});el("content").append(grid)}

async function skillPage(id){title("Управление skill");activate("/skills");const item=await api(`/api/skills/${encodeURIComponent(id)}`);clear();const c=card(item.name,true);c.classList.add("full");c.append(badge(item.status),node("p",item.description),node("h3","Manifest"));const manifest={id:item.id,name:item.name,version:item.version,author:item.author,category:item.category,agent:item.agent,risk:item.risk,sandbox:item.sandbox,approval_required:item.approval_required,permissions:item.permissions,tools:item.tools};c.append(node("pre",JSON.stringify(manifest,null,2)));const actions=node("div",undefined,"actions");[["enable","Enable","primary"],["disable","Disable","secondary"],["reload","Reload","primary"]].forEach(([action,label,cls])=>{const b=node("button",label,cls);b.onclick=async()=>{b.disabled=true;try{const result=await api(`/api/skills/${id}/${action}`,{method:"POST",body:"{}"});alert(`Создано подтверждение ${result.approval_id}`);navigate("/approvals")}catch(e){alert(e.message);b.disabled=false}};actions.append(b)});c.append(actions,node("h3","Lifecycle"));item.events.forEach(event=>{const r=node("div",undefined,"health-row");r.append(node("span",event.event),node("small",`${event.result} · ${fmt(event.created_at)}`,"muted"));c.append(r)});el("content").append(c)}

async function templatesPage(){title("Workflow Templates");activate("/templates");const data=await api("/api/templates");clear();const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.name);c.append(badge(item.status),node("p",`Version: ${item.version} · Agents: ${item.agents.length} · Skills: ${item.skills.length}`,"muted"),node("p",`Risk: ${item.risk}`));const more=node("button","Inspect","secondary");more.onclick=()=>navigate(`/templates/${item.id}`);c.append(more);grid.append(c)});el("content").append(grid)}

async function templatePage(id){title("Template details");activate("/templates");const item=await api(`/api/templates/${encodeURIComponent(id)}`);clear();const c=card(item.name,true);c.classList.add("full");c.append(badge(item.status),node("p",item.description),node("h3","Manifest"),node("pre",JSON.stringify({id:item.id,version:item.version,agents:item.agents,skills:item.skills,permissions:item.permissions,approval_required:item.approval_required},null,2)));const install=node("button",item.approval_required?"Install with approval":"Install","primary");install.disabled=item.status!=="ACTIVE";install.onclick=async()=>{install.disabled=true;try{const result=await api(`/api/templates/${id}/install`,{method:"POST",body:"{}"});if(result.approval_id){alert(`Approval created: ${result.approval_id}`);navigate("/approvals")}else{alert("Template installed");navigate("/templates")}}catch(e){alert(e.message);install.disabled=false}};c.append(install);el("content").append(c)}

async function playgroundPage(){title("Safe Playground");activate("/playground");const data=await api("/api/playground/examples");clear();const notice=card("Sandbox-only examples",true);notice.classList.add("full");notice.append(node("p","No external writes, publishing, secrets, or production tools are available.","muted"));const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.name);c.append(node("p",`Agent: ${item.agent} · Input: ${item.input_type}`,"muted"),badge(data.mode));grid.append(c)});el("content").append(notice,grid)}

async function organizationsPage(){title("Organizations");activate("/organizations");const data=await api("/api/organizations");clear();const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.name);c.append(badge(item.status),node("p",`ID: ${item.id}`,"muted"));grid.append(c)});el("content").append(grid)}

async function workspacesPage(){title("Workspaces");activate("/workspaces");const data=await api("/api/workspaces");clear();const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.name);c.append(badge(item.status),node("p",item.description||"No description"),node("p",`Members: ${item.members} · Agents: ${item.agents} · Tasks: ${item.tasks} · Skills: ${item.skills}`,"muted"),node("p",`Role: ${item.role}`,"muted"));grid.append(c)});el("content").append(grid)}

async function membersPage(){title("Members");activate("/members");const workspaces=await api("/api/workspaces");clear();if(!workspaces.items.length){el("content").append(node("div","No accessible workspace","empty"));return}const workspace=workspaces.items[0];const data=await api(`/api/members?workspace_id=${encodeURIComponent(workspace.id)}`);const c=card(`${workspace.name} members`,true);c.classList.add("full");data.items.forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",item.display_name),badge(item.role));c.append(row)});el("content").append(c)}

async function knowledgePage(){title("Knowledge Base");activate("/knowledge");const workspaces=await api("/api/workspaces");clear();if(!workspaces.items.length){el("content").append(node("div","No accessible workspace","empty"));return}const workspace=workspaces.items[0];const data=await api(`/api/knowledge?workspace_id=${encodeURIComponent(workspace.id)}`);const c=card(`${workspace.name} knowledge`,true);c.classList.add("full");if(!data.items.length)c.append(node("div","Knowledge documents not found","empty"));data.items.forEach(item=>{const row=node("div",undefined,"approval-row");const info=node("div");info.append(node("strong",item.name),node("p",`${item.type} · ${item.access_level}`,"muted"));row.append(info);c.append(row)});el("content").append(c)}

function choice(name,value,label){const wrap=node("label",undefined,"choice");const input=node("input");input.type="checkbox";input.name=name;input.value=value;wrap.append(input,node("span",label));return wrap}

async function apiKeysPage(){title("API Keys");activate("/api-keys");clear();const form=card("Создать API key",true);const name=node("input");name.placeholder="Название ключа";name.maxLength=100;const expiry=node("input");expiry.type="datetime-local";const scopes=node("div",undefined,"actions");["tasks:create","tasks:read","agents:read","skills:read","webhooks:manage"].forEach(scope=>scopes.append(choice("scope",scope,scope)));const create=node("button","Создать через approval","primary");form.append(name,expiry,scopes,create);create.onclick=async()=>{create.disabled=true;try{const selected=[...scopes.querySelectorAll("input:checked")].map(x=>x.value);const expires_at=expiry.value?new Date(expiry.value).toISOString():null;const result=await api("/api/platform/api-keys",{method:"POST",body:JSON.stringify({name:name.value,scopes:selected,expires_at})});alert(`Создано подтверждение ${result.approval_id}`);navigate("/approvals")}catch(e){alert(e.message);create.disabled=false}};const list=card("Ключи",true);list.classList.add("full");const data=await api("/api/platform/api-keys");if(!data.items.length)list.append(node("div","API keys пока нет","empty"));data.items.forEach(item=>{const row=node("div",undefined,"approval-row");const info=node("div");info.append(node("strong",item.name),node("p",`${item.id} · ${item.scopes.join(", ")} · expires ${fmt(item.expires_at)}`,"muted"));row.append(info,badge(item.status));if(item.status!=="PENDING"){const actions=node("div",undefined,"actions");[["disable","Disable"],["delete","Delete"]].forEach(([action,label])=>{const b=node("button",label,"secondary");b.onclick=async()=>{const result=await api(`/api/platform/api-keys/${item.id}/${action}`,{method:"POST",body:"{}"});alert(`Создано подтверждение ${result.approval_id}`);navigate("/approvals")};actions.append(b)});row.append(actions)}list.append(row)});el("content").append(form,list)}

async function webhooksPage(){title("Webhooks");activate("/webhooks");clear();const form=card("Новый webhook",true);const url=node("input");url.placeholder="https://example.com/nexora-events";const events=node("div",undefined,"actions");["TASK_CREATED","TASK_COMPLETED","TASK_FAILED","APPROVAL_REQUIRED","SECURITY_EVENT"].forEach(event=>events.append(choice("event",event,event)));const create=node("button","Добавить через approval","primary");form.append(url,events,create);create.onclick=async()=>{create.disabled=true;try{const selected=[...events.querySelectorAll("input:checked")].map(x=>x.value);const result=await api("/api/platform/webhooks",{method:"POST",body:JSON.stringify({url:url.value,events:selected})});alert(`Создано подтверждение ${result.approval_id}`);navigate("/approvals")}catch(e){alert(e.message);create.disabled=false}};const list=card("Webhook endpoints",true);list.classList.add("full");const data=await api("/api/platform/webhooks");if(!data.items.length)list.append(node("div","Webhooks пока нет","empty"));data.items.forEach(item=>{const row=node("div",undefined,"approval-row");const info=node("div");info.append(node("strong",item.url),node("p",`${item.id} · ${item.events.join(", ")} · failures ${item.failure_count}`,"muted"));row.append(info,badge(item.status));if(item.status!=="PENDING"){const actions=node("div",undefined,"actions");[["disable","Disable"],["delete","Delete"]].forEach(([action,label])=>{const b=node("button",label,"secondary");b.onclick=async()=>{const result=await api(`/api/platform/webhooks/${item.id}/${action}`,{method:"POST",body:"{}"});alert(`Создано подтверждение ${result.approval_id}`);navigate("/approvals")};actions.append(b)});row.append(actions)}list.append(row)});el("content").append(form,list)}

async function metricsPage(){title("Metrics");activate("/metrics");const data=await api("/api/platform/metrics");clear();const c=card("Usage metrics",true);c.classList.add("full");const values=node("div",undefined,"metrics");values.append(metric("Tasks today",data.tasks_today),metric("Success",`${data.success_percent}%`),metric("Average",`${data.average_seconds}s`),metric("Active agents",data.active_agents));c.append(values,node("h3","Agents"));data.agents.forEach(item=>{const r=node("div",undefined,"health-row");r.append(node("span",item.agent),node("strong",`${item.uses} uses · ${item.errors} errors`));c.append(r)});el("content").append(c)}

async function integrationsPage(){title("Integrations");activate("/integrations");const data=await api("/api/platform/integrations");clear();const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.id);c.append(badge(item.status),node("pre",JSON.stringify(item,null,2)));grid.append(c)});el("content").append(grid)}

async function approvalsPage(){title("Approval Center");activate("/approvals");const data=await api("/api/approvals");clear();const c=card("Подтверждения",true);c.classList.add("full");if(!data.items.length)c.append(node("div","Подтверждений пока нет","empty"));data.items.forEach(item=>{const row=node("div",undefined,"approval-row");const info=node("div");info.append(node("strong",item.action_summary||item.action_type),node("p",`Task: ${item.task_id} · Истекает: ${fmt(item.expires_at)}`,"muted"));row.append(info,badge(item.status));if(item.status==="PENDING"){const actions=node("div",undefined,"actions");[["approve","Approve","primary"],["reject","Reject","secondary"]].forEach(([decision,label,cls])=>{const b=node("button",label,cls);b.onclick=async()=>{b.disabled=true;try{const result=await api(`/api/approvals/${item.id}/${decision}`,{method:"POST",body:"{}"});if(result.one_time_secret)window.prompt(result.secret_notice,result.one_time_secret);await approvalsPage()}catch(e){alert(e.message);b.disabled=false}};actions.append(b)});row.append(actions)}c.append(row)});el("content").append(c)}

async function auditPage(){title("Audit Viewer");activate("/audit");clear();const toolbar=node("form",undefined,"toolbar");const severity=node("select");["","INFO","WARNING","SECURITY","ERROR"].forEach(v=>{const o=node("option",v||"Все уровни");o.value=v;severity.append(o)});const source=node("input");source.placeholder="Source";const event=node("input");event.placeholder="Event type";const date=node("input");date.type="date";toolbar.append(severity,source,event,date,node("button","Фильтр","secondary"));const wrap=node("div",undefined,"table-wrap");el("content").append(toolbar,wrap);async function load(e){if(e)e.preventDefault();const q=new URLSearchParams();[["severity",severity.value],["source",source.value],["event",event.value],["date",date.value]].forEach(([k,v])=>{if(v)q.set(k,v)});const data=await api("/api/audit?"+q);const table=node("table");const head=node("tr");["Severity","Event","Source","Result","Time"].forEach(x=>head.append(node("th",x)));const thead=node("thead");thead.append(head);const body=node("tbody");data.items.forEach(item=>{const row=node("tr");const s=node("td");s.append(badge(item.severity));row.append(s,node("td",item.event),node("td",item.source),node("td",item.result),node("td",fmt(item.created_at)));body.append(row)});table.append(thead,body);wrap.replaceChildren(table)}toolbar.onsubmit=load;await load()}

async function ecosystemPage(path,titleText,endpoint){title(titleText);activate(path);const data=await api(endpoint);clear();const c=card(titleText,true);c.classList.add("full");const items=data.items||data.agents||[];if(items.length)items.forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",item.name||item.id),badge(item.status||item.grade||"READY"));c.append(row)});else c.append(node("pre",JSON.stringify(data,null,2)));el("content").append(c)}

async function route(){try{const path=location.pathname;if(path==="/")await dashboard();else if(path==="/tasks")await tasksPage();else if(path.startsWith("/tasks/"))await taskPage(decodeURIComponent(path.slice(7)));else if(path==="/agents")await agentsPage();else if(path.startsWith("/agents/"))await agentPage(decodeURIComponent(path.slice(8)));else if(path==="/skills")await skillsPage();else if(path.startsWith("/skills/"))await skillPage(decodeURIComponent(path.slice(8)));else if(path==="/agent-center")await ecosystemPage(path,"Agent Center","/api/agent-center");else if(path==="/agent-teams")await ecosystemPage(path,"Agent Teams","/api/agent-teams");else if(path==="/agent-memory")await ecosystemPage(path,"Memory 2.0","/api/agent-memory");else if(path==="/agent-planning")await ecosystemPage(path,"Planning Engine","/api/agent-planning");else if(path==="/agent-evaluations")await ecosystemPage(path,"Agent Evaluations","/api/agent-evaluations");else if(path==="/sdk")await ecosystemPage(path,"Nexora SDK","/api/sdk");else if(path==="/api-keys")await apiKeysPage();else if(path==="/webhooks")await webhooksPage();else if(path==="/metrics")await metricsPage();else if(path==="/integrations")await integrationsPage();else if(path==="/approvals")await approvalsPage();else if(path==="/audit")await auditPage();else navigate("/")}catch(error){if(error.message!=="UNAUTHORIZED")errorView(error)}}
const metricsPageV18=metricsPage;
metricsPage=async function(){await metricsPageV18();const data=await api("/api/platform/metrics");const community=card("Community metrics",true);community.classList.add("full");const values=node("div",undefined,"metrics");values.append(metric("Installed templates",data.community.installed_templates),metric("Active skills",data.community.active_skills),metric("Completed demos",data.community.completed_demos));community.append(values);el("content").append(community)};
const apiKeysPageV18=apiKeysPage;
apiKeysPage=async function(){await apiKeysPageV18();const values=["templates:read","templates:install","playground:read","organizations:read","workspaces:read","workspaces:write","members:read","members:invite","knowledge:read","knowledge:write","plans:read","billing:read","usage:read","limits:read","marketplace:read","marketplace:install","marketplace:publish","creators:read","creator:read","agent_ecosystem:read","agent_ecosystem:manage","operations:read","notifications:read"];const last=document.querySelector('input[name="scope"][value="webhooks:manage"]');const container=last&&last.closest(".actions");if(container)values.forEach(scope=>container.append(choice("scope",scope,scope)))};
const routeV20=route;
route=async function(){const path=location.pathname;try{if(path==="/templates")return await templatesPage();if(path.startsWith("/templates/"))return await templatePage(decodeURIComponent(path.slice(11)));if(path==="/playground")return await playgroundPage();return await routeV20()}catch(error){if(error.message!=="UNAUTHORIZED")errorView(error)}};
const routeV21=route;
route=async function(){const path=location.pathname;try{if(path==="/organizations")return await organizationsPage();if(path==="/workspaces")return await workspacesPage();if(path==="/members")return await membersPage();if(path==="/knowledge")return await knowledgePage();return await routeV21()}catch(error){if(error.message!=="UNAUTHORIZED")errorView(error)}};
async function plansPage(){title("Plans");activate("/plans");const data=await api("/api/plans");clear();const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.name);c.append(badge(item.status),node("p",`Tier: ${item.tier}`),node("pre",JSON.stringify({limits:item.limits,features:item.features},null,2)));grid.append(c)});el("content").append(grid)}
async function billingPage(){title("Billing");activate("/billing");const data=await api("/api/billing");clear();const c=card(`Current Plan: ${data.subscription.plan_name}`,true);c.classList.add("full");c.append(badge(data.subscription.status),node("h3","Usage and limits"));Object.entries(data.limits.limits).forEach(([key,value])=>{const row=node("div",undefined,"health-row");const current=data.limits.current[key]||0;row.append(node("span",key),node("strong",`${current} / ${value===null?"Unlimited":value}`));c.append(row)});el("content").append(c)}
async function usagePage(){title("Usage");activate("/usage");const data=await api("/api/usage-v23");clear();const c=card(`Usage ${data.month}`,true);c.classList.add("full");c.append(node("h3","Metered events"),node("pre",JSON.stringify(data.events,null,2)),node("h3","Current resources"),node("pre",JSON.stringify(data.resources,null,2)));el("content").append(c)}
async function adminPage(){title("Admin Console");activate("/admin");const data=await api("/api/admin");clear();const health=card("System Health",true);health.append(node("pre",JSON.stringify(data.system_health,null,2)));const c=card("Organizations / Subscriptions / Usage / Limits",true);c.classList.add("full");data.organizations.forEach(item=>{const row=node("div",undefined,"approval-row");const info=node("div");info.append(node("strong",item.name),node("p",`${item.id} · ${item.plan_id} · ${item.subscription_status}`,"muted"),node("p",`Tasks: ${item.usage.resources.tasks_monthly} · Workspaces: ${item.usage.resources.workspace_limit}`,"muted"));const actions=node("div",undefined,"actions");const plan=node("select");data.plans.forEach(value=>{const option=node("option",value.name);option.value=value.id;plan.append(option)});const change=node("button","Change plan","primary");change.onclick=async()=>{const result=await api(`/api/admin/organizations/${item.id}/plan`,{method:"POST",body:JSON.stringify({plan_id:plan.value})});alert(`Approval created: ${result.approval_id}`);navigate("/approvals")};const block=node("button",item.status==="SUSPENDED"?"Unblock":"Block","secondary");block.onclick=async()=>{const action=item.status==="SUSPENDED"?"unblock":"block";const result=await api(`/api/admin/organizations/${item.id}/${action}`,{method:"POST",body:"{}"});alert(`Approval created: ${result.approval_id}`);navigate("/approvals")};actions.append(plan,change,block);row.append(info,actions);c.append(row)});const security=card("Security Events",true);security.classList.add("full");security.append(node("pre",JSON.stringify(data.security_events,null,2)));el("content").append(health,c,security)}
const routeV22=route;
route=async function(){const path=location.pathname;try{if(path==="/plans")return await plansPage();if(path==="/billing")return await billingPage();if(path==="/usage")return await usagePage();if(path==="/admin")return await adminPage();return await routeV22()}catch(error){if(error.message!=="UNAUTHORIZED")errorView(error)}};
async function marketplacePage(){title("Marketplace");activate("/marketplace");const data=await api("/api/marketplace");clear();const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.name);c.append(badge(item.status),node("p",`${item.type} · ${item.version} · ${item.author}`,"muted"),node("p",item.description),node("p",`Risk: ${item.risk_level} · Downloads: ${item.downloads}`));const open=node("button","View package","secondary");open.onclick=()=>navigate(`/marketplace/${item.id}`);c.append(open);grid.append(c)});el("content").append(data.items.length?grid:node("div","Marketplace catalog is empty","empty"))}
async function marketplaceItemPage(id){title("Marketplace item");activate("/marketplace");const item=await api(`/api/marketplace/${encodeURIComponent(id)}`);const workspaces=await api("/api/workspaces");clear();const c=card(item.name,true);c.classList.add("full");c.append(badge(item.status),node("p",item.description),node("pre",JSON.stringify({type:item.type,version:item.version,author:item.author,risk:item.risk_level,permissions:item.manifest.permissions,security:item.manifest.security,checksum:item.checksum,signature_status:item.signature_status},null,2)));if(workspaces.items.length){const select=node("select");workspaces.items.forEach(ws=>{const o=node("option",ws.name);o.value=ws.id;select.append(o)});const install=node("button","Install","primary");install.onclick=async()=>{install.disabled=true;try{const result=await api(`/api/marketplace/${id}/install`,{method:"POST",body:JSON.stringify({workspace_id:select.value,version:item.version})});if(result.approval_id){alert(`Approval created: ${result.approval_id}`);navigate("/approvals")}else{alert("Installed")}}catch(e){alert(e.message);install.disabled=false}};c.append(select,install)}el("content").append(c)}
async function myItemsPage(){title("My marketplace items");activate("/my-items");const data=await api("/api/my-items");clear();const c=card("Published items",true);c.classList.add("full");data.items.forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",`${item.name} ${item.version}`),badge(item.status));c.append(row)});if(!data.items.length)c.append(node("div","No published items","empty"));el("content").append(c)}
async function publisherPage(){title("Publisher");activate("/publisher");const data=await api("/api/publisher");clear();const form=card("Register publisher",true);const name=node("input");name.placeholder="Publisher display name";const register=node("button","Register with approval","primary");register.onclick=async()=>{register.disabled=true;try{const result=await api("/api/publisher/register",{method:"POST",body:JSON.stringify({display_name:name.value})});alert(`Approval created: ${result.approval_id}`);navigate("/approvals")}catch(e){alert(e.message);register.disabled=false}};form.append(name,register);const list=card("Publisher identities",true);data.publishers.forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",item.display_name),badge(item.status));list.append(row)});el("content").append(form,list)}
async function creatorPage(){title("Creator Dashboard");activate("/creator");const data=await api("/api/creator");clear();if(!data.configured){const form=card("Create creator profile",true);const name=node("input");name.placeholder="Display name";const bio=node("input");bio.placeholder="Bio";const create=node("button","Create profile","primary");create.onclick=async()=>{create.disabled=true;try{await api("/api/creator/profile",{method:"POST",body:JSON.stringify({display_name:name.value,bio:bio.value})});await creatorPage()}catch(e){alert(e.message);create.disabled=false}};form.append(name,bio,create);el("content").append(form);return}const p=data.profile;const profile=card(p.display_name,true);profile.append(badge(p.status),node("p",p.bio||"No bio","muted"),node("p",`Verification: ${p.level||"NEW_CREATOR"}`));const metrics=card("Analytics",true);const s=data.analytics.summary;metrics.append(node("p",`Packages: ${s.packages} · Installs: ${s.total_installs} · Active: ${s.active_installations}`),node("p",`Executions: ${s.executions} · Success: ${s.success_rate}% · Rating: ${s.rating}`));const packages=card("My Packages",true);data.packages.forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",`${item.package_id} ${item.version}`),badge(item.status));packages.append(row)});if(!data.packages.length)packages.append(node("div","No packages","empty"));const sections=card("Creator tools",true);sections.append(node("p","My Packages · Analytics · Reviews · Verification · Settings","muted"));el("content").append(profile,metrics,packages,sections)}
const routeV23=route;
route=async function(){const path=location.pathname;try{if(path==="/marketplace")return await marketplacePage();if(path.startsWith("/marketplace/"))return await marketplaceItemPage(decodeURIComponent(path.slice(13)));if(path==="/my-items")return await myItemsPage();if(path==="/publisher")return await publisherPage();if(path==="/creator")return await creatorPage();return await routeV23()}catch(error){if(error.message!=="UNAUTHORIZED")errorView(error)}};

const REALTIME_EVENTS=["TASK_CREATED","TASK_STARTED","TASK_PROGRESS_UPDATED","TASK_STAGE_CHANGED","AGENT_STARTED","AGENT_FINISHED","TASK_COMPLETED","TASK_FAILED","APPROVAL_REQUIRED"];
function connectRealtime(workspaceId,cursor){
  if(!workspaceId)return;
  if(state.realtime&&state.realtimeWorkspace===workspaceId)return;
  if(state.realtime)state.realtime.close();
  const query=new URLSearchParams({workspace_id:workspaceId});if(cursor)query.set("after",cursor);
  const stream=new EventSource("/api/realtime/tasks?"+query);
  if(!state.realtimeSeen)state.realtimeSeen=new Set();
  REALTIME_EVENTS.forEach(type=>stream.addEventListener(type,event=>{try{const eventId=event.lastEventId||"";if(eventId&&state.realtimeSeen.has(eventId))return;if(eventId){state.realtimeSeen.add(eventId);if(state.realtimeSeen.size>500)state.realtimeSeen.clear()}const value=JSON.parse(event.data);scheduleNotificationRefresh();if(state.realtimeCallback)state.realtimeCallback(value)}catch{}}));
  stream.onopen=()=>{el("connection").textContent="Realtime подключён";el("connection").classList.remove("warning")};
  stream.onerror=()=>{el("connection").textContent="Восстановление realtime…";el("connection").classList.add("warning")};
  state.realtime=stream;state.realtimeWorkspace=workspaceId;
}

const tasksPageV342Base=tasksPage;
tasksPage=async function(){
  await tasksPageV342Base();
  const summary=await api("/api/dashboard");
  const refresh=node("button","Обновить","secondary");
  refresh.type="button";refresh.dataset.realtimeFallback="true";refresh.onclick=()=>tasksPage().catch(errorView);
  const notice=el("content").querySelector("article.card");if(notice)notice.append(refresh);
  state.realtimeCallback=()=>tasksPage().catch(errorView);
  connectRealtime(summary.workspace.id,summary.realtime_cursor);
};

const taskPageV342Base=taskPage;
taskPage=async function(id){
  await taskPageV342Base(id);
  const summary=await api("/api/dashboard");
  const refresh=node("button","Обновить","secondary");
  refresh.type="button";refresh.dataset.realtimeFallback="true";refresh.onclick=()=>taskPage(id).catch(errorView);
  const details=el("content").querySelector("article.card");if(details)details.append(refresh);
  state.realtimeCallback=event=>{if(event&&event.task_id===id)taskPage(id).catch(errorView)};
  connectRealtime(summary.workspace.id,summary.realtime_cursor);
};

function feedRow(item){const row=node("div",undefined,"activity-item");const marker=node("span","","activity-marker");const info=node("div");info.append(node("strong",item.message||item.type),node("p",[item.resource_id,item.stage,item.progress===null||item.progress===undefined?null:`${item.progress}%`].filter(Boolean).join(" · ")||"Без дополнительных данных","muted"));row.append(marker,info,node("small",fmt(item.timestamp||item.created_at),"muted"));return row}

async function homePage(){
  title("Главная");activate("/home");
  const data=await api("/api/dashboard");const workspace=data.workspace.id;const [activity,notifications]=await Promise.all([api(`/api/activity?workspace_id=${encodeURIComponent(workspace)}&limit=6`),api(`/api/notifications?workspace_id=${encodeURIComponent(workspace)}&limit=5`)]);
  clear();const welcome=card(data.welcome,true);welcome.classList.add("full");welcome.append(node("p",`Workspace: ${data.workspace.name}`,"muted"));const values=node("div",undefined,"metrics operations-metrics");values.append(metric("Активные задачи",data.active_tasks),metric("Завершено",data.completed_tasks),metric("Работающие агенты",data.running_agents),metric("Ожидают подтверждения",data.pending_approvals),metric("Непрочитанные",data.unread_notifications),metric("Использование",`${data.usage_percent}%`));welcome.append(values);
  if(!data.onboarding.completed){const start=node("button","Пройти первый запуск","primary");start.onclick=()=>navigate("/onboarding");welcome.append(node("p","Настройте безопасный первый сценарий Nexora.","muted"),start)}
  const feed=card("Последняя активность",true);feed.classList.add("wide");(activity.items||[]).forEach(item=>feed.append(feedRow(item)));if(!activity.items.length)feed.append(node("div","Событий пока нет","empty"));
  const notices=card(`Уведомления · ${notifications.unread}`);(notifications.items||[]).forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",item.message),badge(item.status));notices.append(row)});if(!notifications.items.length)notices.append(node("div","Новых уведомлений нет","empty"));
  const grid=node("div",undefined,"grid");grid.append(feed,notices);el("content").append(welcome,grid);
  state.realtimeCallback=()=>homePage().catch(errorView);connectRealtime(workspace,data.realtime_cursor);
}

async function activityPage(){title("Активность");activate("/activity");const summary=await api("/api/dashboard");const data=await api(`/api/activity?workspace_id=${encodeURIComponent(summary.workspace.id)}&limit=100`);clear();const c=card("Activity Feed",true);c.classList.add("full");(data.items||[]).forEach(item=>c.append(feedRow(item)));if(!data.items.length)c.append(node("div","Событий пока нет","empty"));el("content").append(c);state.realtimeCallback=()=>activityPage().catch(errorView);connectRealtime(summary.workspace.id,summary.realtime_cursor)}

async function notificationsPage(){title("Уведомления");activate("/notifications");const summary=await api("/api/dashboard");const data=await api(`/api/notifications?workspace_id=${encodeURIComponent(summary.workspace.id)}&limit=100`);clear();const c=card(`Уведомления · непрочитанных ${data.unread}`,true);c.classList.add("full");(data.items||[]).forEach(item=>{const row=node("div",undefined,"approval-row");const info=node("div");info.append(node("strong",item.message),node("p",`${item.type} · ${fmt(item.created_at)}`,"muted"));row.append(info,badge(item.status));if(item.status==="UNREAD"){const read=node("button","Прочитано","secondary");read.onclick=async()=>{read.disabled=true;await api(`/api/notifications/${item.id}/read?workspace_id=${encodeURIComponent(summary.workspace.id)}`,{method:"POST",body:"{}"});await notificationsPage()};row.append(read)}c.append(row)});if(!data.items.length)c.append(node("div","Уведомлений пока нет","empty"));el("content").append(c);state.realtimeCallback=()=>notificationsPage().catch(errorView);connectRealtime(summary.workspace.id,summary.realtime_cursor)}

async function workspaceOverviewPage(){title("Workspace Overview");activate("/workspace");const data=await api("/api/workspace-overview");clear();const c=card(data.name,true);c.classList.add("full");c.append(badge(data.role));const values=node("div",undefined,"metrics operations-metrics");values.append(metric("Участники",data.members),metric("Агенты",data.agents),metric("Задачи",data.tasks),metric("Навыки",data.skills),metric("Использование",`${data.usage_percent}%`));c.append(values,node("p","Данные ограничены текущим workspace и доступны только после RBAC-проверки.","muted"));el("content").append(c)}

async function agentStatusPage(){title("Agent Status Center");activate("/agents/status");const summary=await api("/api/dashboard");const data=await api(`/api/agents/status?workspace_id=${encodeURIComponent(summary.workspace.id)}`);clear();const grid=node("div",undefined,"grid");data.items.forEach(item=>{const c=card(item.name);c.append(badge(item.status),badge(item.health),node("p",item.current_task?`Текущая задача: ${item.current_task.title}`:"Текущей задачи нет","muted"),node("p",`Последняя активность: ${fmt(item.last_execution)}`,"muted"));if(item.error_code)c.append(node("p",`Код ошибки: ${item.error_code}`,"danger"));grid.append(c)});el("content").append(data.items.length?grid:node("div","Агенты не настроены для workspace","empty"));state.realtimeCallback=()=>agentStatusPage().catch(errorView);connectRealtime(summary.workspace.id,summary.realtime_cursor)}

async function operationsAnalyticsPage(){title("Operations Analytics");activate("/analytics");const data=await api("/api/operations/analytics");clear();const overview=card("Операционные метрики",true);overview.classList.add("full");const values=node("div",undefined,"metrics operations-metrics");values.append(metric("Создано",data.tasks.created),metric("Завершено",data.tasks.completed),metric("Ошибки",data.tasks.failed),metric("Успешность",`${data.tasks.success_rate}%`),metric("Среднее время",`${data.tasks.average_duration_seconds} сек`));overview.append(values);const agents=card("Агенты",true);data.agents.forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",item.agent),node("strong",`${item.executions} запусков · ${item.success_rate}% · ошибок ${item.errors}`));agents.append(row)});if(!data.agents.length)agents.append(node("div","Данных пока недостаточно","empty"));const workflows=card("Workflows",true);(data.workflows.items||[]).forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",item.workflow),node("strong",`${item.executions} запусков · ${item.success_rate}% · ошибок ${item.errors}`));workflows.append(row)});if(!data.workflows.items?.length)workflows.append(node("div","Данных пока недостаточно","empty"));const bottlenecks=card("Этапы");(data.workflows.bottlenecks||[]).forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",item.stage),node("strong",item.events));bottlenecks.append(row)});if(!data.workflows.bottlenecks.length)bottlenecks.append(node("div","Данных пока недостаточно","empty"));const grid=node("div",undefined,"grid");grid.append(agents,workflows,bottlenecks);el("content").append(overview,grid)}

async function onboardingPage(){title("Первый запуск");activate("/home");clear();const c=card("Welcome to Nexora",true);c.classList.add("full","onboarding");[["1","Выберите Workspace","Работайте только в нужном изолированном пространстве.","/workspace"],["2","Выберите Template","Используйте проверенный шаблон без расширения разрешений.","/templates"],["3","Создайте первую задачу","Откройте Task Center и следуйте безопасному сценарию.","/tasks"],["4","Проверьте результат","Статус, события и результат доступны в карточке задачи.","/tasks"]].forEach(([number,label,description,path])=>{const step=node("button",undefined,"onboarding-step");step.append(node("span",number,"step-number"),node("strong",label),node("small",description,"muted"));step.onclick=()=>navigate(path);c.append(step)});c.append(node("p","Onboarding не запускает внешние интеграции, публикации или production-действия.","muted"));el("content").append(c)}

function requestKey(prefix="web"){
  const suffix=globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

function taskProgress(item){
  const wrap=node("div",undefined,"workbench-progress");
  const labels=node("div",undefined,"workbench-progress-labels");
  labels.append(node("strong",item.stage||item.status||"NEW"),node("span",`${Number(item.progress||0)}%`));
  const track=node("div",undefined,"progress-track");
  const value=node("span",undefined,"progress-value");
  value.style.width=`${Math.max(0,Math.min(100,Number(item.progress||0)))}%`;
  track.append(value);wrap.append(labels,track);return wrap;
}

function taskSummaryRow(item){
  const row=node("button",undefined,"workbench-task-row");row.type="button";
  const info=node("div");info.append(node("strong",item.title||item.task_id),node("small",`${item.assigned_agent||"Orchestrator"} · ${fmt(item.updated_at)}`,"muted"));
  const meta=node("div",undefined,"task-row-meta");meta.append(badge(item.status),node("span",`${item.progress||0}%`));
  row.append(info,meta);row.onclick=()=>navigate(`/workbench/tasks/${encodeURIComponent(item.task_id)}`);return row;
}

async function workbenchPage(){
  title("Nexora Workbench");activate("/workbench");
  const [summary,tasks,agents]=await Promise.all([api("/api/dashboard"),api("/api/tasks?limit=12"),api("/api/agents")]);
  clear();
  const overview=node("section",undefined,"workbench-overview");
  overview.append(
    metric("Активные задачи",summary.active_tasks),
    metric("Завершено",summary.completed_tasks),
    metric("Доступные агенты",(agents.items||[]).filter(item=>item.status!=="DISABLED").length),
    metric("Ожидают подтверждения",summary.pending_approvals)
  );
  const hero=node("section",undefined,"workbench-hero");
  const copy=node("div",undefined,"workbench-copy");
  copy.append(node("p","NEXORA AGENT WORKBENCH","eyebrow"),node("h2","Поставьте задачу своей AI-команде"),node("p","Опишите ожидаемый результат обычными словами. Orchestrator безопасно подберёт специалиста, workflow и доступные инструменты.","muted"));
  const routeInfo=node("div",undefined,"workbench-route-info");
  routeInfo.append(badge("Автоподбор агента"),node("span","Policy Engine → Workflow → Result","muted"));
  copy.append(routeInfo);
  const form=node("form",undefined,"workbench-composer");
  const input=node("textarea");input.name="message";input.placeholder="Например: проанализируй идею Telegram-бота для учёта расходов и подготовь план MVP";input.maxLength=12000;input.required=true;
  const submit=node("button","Запустить агентов","primary");submit.type="submit";
  const hint=node("small",`Workspace: ${summary.workspace.name} · production-действия не выполняются без approval`,"muted");
  form.append(input,submit,hint);
  form.onsubmit=async event=>{event.preventDefault();const message=input.value.trim();if(!message)return;submit.disabled=true;submit.textContent="Создаём задачу…";try{const result=await api("/api/workbench/tasks",{method:"POST",body:JSON.stringify({message,workspace_id:summary.workspace.id,idempotency_key:requestKey("task")})});navigate(`/workbench/tasks/${encodeURIComponent(result.task_id||result.id)}`)}catch(error){submit.disabled=false;submit.textContent="Запустить агентов";alert(error.message)}};
  const suggestions=node("div",undefined,"prompt-suggestions");
  ["Подготовь план запуска SaaS-продукта","Проанализируй архитектуру и найди риски","Создай контент-план на месяц","Подготовь исследование рынка"].forEach(text=>{const button=node("button",text,"prompt-chip");button.type="button";button.onclick=()=>{input.value=text;input.focus()};suggestions.append(button)});
  form.append(suggestions);hero.append(copy,form);
  const team=card("Доступная AI-команда",true);team.classList.add("full","workbench-team");
  const roster=node("div",undefined,"workbench-agent-roster");
  (agents.items||[]).filter(item=>item.status!=="DISABLED").slice(0,8).forEach(item=>{
    const agent=node("button",undefined,"workbench-agent");agent.type="button";
    agent.append(node("span",undefined,"agent-dot"),node("strong",item.name),node("small",item.description||item.role,"muted"));
    agent.title="Orchestrator назначает агента автоматически";agent.onclick=()=>navigate(`/agents/${encodeURIComponent(item.id)}`);
    roster.append(agent);
  });
  if(!roster.childNodes.length)roster.append(node("div","Активные агенты пока недоступны.","empty"));
  team.append(node("p","Специалист назначается автоматически с учётом политики и типа задачи. Нажмите на агента, чтобы посмотреть его возможности.","muted"),roster);
  const recent=card("Последние задачи",true);recent.classList.add("full","workbench-recent");
  const filters=node("div",undefined,"workbench-task-filters");
  const taskList=node("div",undefined,"workbench-task-list");
  const busy=new Set(["NEW","CLARIFYING","QUEUED","PLANNING","IN_PROGRESS","WAITING_APPROVAL"]);
  const renderTasks=filter=>{
    const visible=(tasks.items||[]).filter(item=>filter==="active"?busy.has(item.status):filter==="completed"?item.status==="COMPLETED":true);
    taskList.replaceChildren();
    visible.forEach(item=>taskList.append(taskSummaryRow(item)));
    if(!visible.length)taskList.append(node("div","В этой категории задач пока нет.","empty"));
    filters.querySelectorAll("button").forEach(button=>button.classList.toggle("active",button.dataset.filter===filter));
  };
  [["all","Все"],["active","В работе"],["completed","Готовые"]].forEach(([value,label])=>{const button=node("button",label,"secondary");button.type="button";button.dataset.filter=value;button.onclick=()=>renderTasks(value);filters.append(button)});
  const allTasks=node("button","Открыть все задачи","secondary");allTasks.type="button";allTasks.onclick=()=>navigate("/tasks");filters.append(allTasks);
  recent.append(filters,taskList);renderTasks("all");
  el("content").append(overview,hero,team,recent);
}

async function workbenchTaskPage(id){
  title("Выполнение задачи");activate("/workbench");
  const encoded=encodeURIComponent(id);
  const [summary,item,timeline]=await Promise.all([api("/api/dashboard"),api(`/api/tasks/${encoded}`),api(`/api/tasks/${encoded}/events`)]);
  clear();
  const header=node("section",undefined,"workbench-task-header");
  const identity=node("div");identity.append(node("p",item.task_id,"eyebrow"),node("h2",item.title||"Задача Nexora"),node("p",item.description||"Описание задачи","muted"));
  const status=node("div",undefined,"workbench-task-status");status.append(badge(item.status),taskProgress(item));header.append(identity,status);
  const layout=node("div",undefined,"workbench-layout");
  const result=card(item.status==="COMPLETED"?"Готовый результат":"Ход выполнения",true);result.classList.add("workbench-result");
  if(item.status==="COMPLETED")result.append(node("pre",item.result_summary||"Задача завершена без текстового результата."));
  else if(item.status==="FAILED")result.append(node("p",`Задача остановлена. Код: ${item.error_code||"NX_INTERNAL_ERROR"}`,"danger"));
  else if(item.status==="CANCELLED")result.append(node("p","Задача отменена. Уже созданные результаты не удалялись.","muted"));
  else result.append(node("div","Агенты выполняют задачу. Значимые этапы появятся здесь автоматически.","workbench-running"));
  const actionBar=node("div",undefined,"actions");
  if((item.downloads||[]).length){const download=node("a","Скачать результат .txt","button-link");download.href=`/api/tasks/${encoded}/downloads/result`;download.download=item.downloads[0].name;actionBar.append(download)}
  if(item.status==="WAITING_APPROVAL"){const approval=node("button","Открыть подтверждение","primary");approval.onclick=()=>navigate("/approvals");actionBar.append(approval)}
  if(["NEW","CLARIFYING","QUEUED","PLANNING","IN_PROGRESS","WAITING_APPROVAL"].includes(item.status)){const cancel=node("button","Отменить задачу","secondary");cancel.onclick=async()=>{if(!confirm("Отменить текущую задачу? Созданные результаты удалены не будут."))return;cancel.disabled=true;try{await api(`/api/workbench/tasks/${encoded}/cancel`,{method:"POST",body:JSON.stringify({workspace_id:summary.workspace.id})});await workbenchTaskPage(id)}catch(error){cancel.disabled=false;alert(error.message)}};actionBar.append(cancel)}
  if(item.status==="COMPLETED"){const follow=node("form",undefined,"workbench-followup");const message=node("textarea");message.placeholder="Уточните или продолжите задачу…";message.maxLength=12000;message.required=true;const send=node("button","Продолжить","primary");follow.append(message,send);follow.onsubmit=async event=>{event.preventDefault();send.disabled=true;try{await api(`/api/workbench/tasks/${encoded}/messages`,{method:"POST",body:JSON.stringify({message:message.value,workspace_id:summary.workspace.id,idempotency_key:requestKey("message")})});await workbenchTaskPage(id)}catch(error){send.disabled=false;alert(error.message)}};result.append(follow)}
  result.append(actionBar);
  const timelineCard=card("Этапы",true);timelineCard.classList.add("workbench-timeline");
  (timeline.items||[]).forEach(event=>timelineCard.append(feedRow({message:event.type,resource_id:event.agent||event.workflow,stage:event.stage,progress:event.progress,timestamp:event.timestamp})));
  if(!timeline.items?.length)timelineCard.append(node("div","События появятся после запуска workflow.","empty"));
  layout.append(result,timelineCard);el("content").append(header,layout);
  state.realtimeCallback=event=>{if(event?.task_id===id)workbenchTaskPage(id).catch(errorView)};
  connectRealtime(summary.workspace.id,summary.realtime_cursor);
}

const WORKFORCE_CATEGORIES=["","business","marketing","development","analytics","support","hr","finance","automation","content"];
const WORKFORCE_KIND={employees:"EMPLOYEE",workflows:"WORKFLOW",skills:"SKILL"};

function workforcePrice(item){return Number(item.price_cents||0)===0?"Free":`${(Number(item.price_cents)/100).toFixed(2)} ${item.currency||"USD"}`}
function workforceCard(item,workspaceId){
  const c=card(item.name);c.classList.add("marketplace-v4-card");
  const badges=node("div",undefined,"actions");badges.append(badge(item.listing_kind),badge(item.risk_level),badge(workforcePrice(item)));c.append(badges);
  c.append(node("p",item.description),node("p",`${item.author} · v${item.version} · ${item.downloads||0} установок`,"muted"),node("p",(item.tags||[]).join(" · "),"muted"));
  const footer=node("div",undefined,"marketplace-card-footer");footer.append(node("strong",item.installation_status==="ACTIVE"?"Установлен":workforcePrice(item)));
  const open=node("button","Подробнее","secondary");open.onclick=()=>navigate(`/marketplace/item/${encodeURIComponent(item.id)}`);footer.append(open);c.append(footer);return c;
}

async function workforceMarketplacePage(kind="EMPLOYEE"){
  const routePath=kind==="WORKFLOW"?"/marketplace/workflows":kind==="SKILL"?"/marketplace/skills":"/marketplace";
  title(kind==="WORKFLOW"?"Workflow Store":kind==="SKILL"?"Skill Store":"AI Workforce Marketplace");activate(routePath);
  const summary=await api("/api/dashboard");clear();
  const hero=node("section",undefined,"marketplace-v4-hero");hero.append(node("p","NEXORA MARKETPLACE","eyebrow"),node("h2",kind==="EMPLOYEE"?"Наймите готового AI-сотрудника":kind==="WORKFLOW"?"Установите готовый процесс":"Расширьте возможности команды"),node("p","Проверенные декларативные пакеты. Без shell, Docker socket и прямого доступа к секретам.","muted"));
  const filters=node("form",undefined,"marketplace-filters");const search=node("input");search.placeholder="Поиск";const category=node("select");WORKFORCE_CATEGORIES.forEach(value=>{const option=node("option",value?value[0].toUpperCase()+value.slice(1):"Все категории");option.value=value;category.append(option)});filters.append(search,category,node("button","Найти","secondary"));
  const grid=node("div",undefined,"grid marketplace-v4-grid");el("content").append(hero,filters,grid);
  async function load(event){if(event)event.preventDefault();const q=new URLSearchParams({workspace_id:summary.workspace.id,kind});if(search.value.trim())q.set("search",search.value.trim());if(category.value)q.set("category",category.value);const data=await api("/api/workforce/catalog?"+q);grid.replaceChildren(...(data.items||[]).map(item=>workforceCard(item,summary.workspace.id)));if(!data.items?.length)grid.append(node("div","Ничего не найдено","empty"))}
  filters.onsubmit=load;await load();
}

async function workforceItemPage(id){
  title("Marketplace Package");activate("/marketplace");const summary=await api("/api/dashboard");const q=`workspace_id=${encodeURIComponent(summary.workspace.id)}`;const item=await api(`/api/workforce/catalog/${encodeURIComponent(id)}?${q}`);clear();
  const hero=node("section",undefined,"marketplace-item-hero");const main=node("div");main.append(node("p",`${item.listing_kind} · ${item.category}`,"eyebrow"),node("h2",item.name),node("p",item.description),node("p",`${item.author} · v${item.version} · рейтинг ${item.rating||"—"} · ${item.downloads||0} установок`,"muted"));const price=node("div",undefined,"marketplace-price");price.append(node("strong",workforcePrice(item)),badge(item.risk_level));hero.append(main,price);
  const details=node("div",undefined,"workforce-details");const permissions=card("Разрешения");permissions.append(node("pre",JSON.stringify(item.manifest.permissions,null,2)));const compatibility=card("Совместимость");compatibility.append(node("pre",JSON.stringify(item.compatibility,null,2)));const changelog=card("Changelog");changelog.append(node("p",item.changelog||"Нет записей","muted"));details.append(permissions,compatibility,changelog);
  const actions=card("Установка",true);actions.classList.add("full");const installation=item.installation;const install=node("button",installation?.status==="ACTIVE"?"Обновить":"Установить","primary");install.onclick=async()=>{install.disabled=true;try{const response=await api(`/api/workforce/${item.id}/${installation?.status==="ACTIVE"?"update":"install"}`,{method:"POST",body:JSON.stringify({workspace_id:summary.workspace.id,version:item.version,auto_update:false})});if(response.approval_id){alert(`Требуется подтверждение ${response.approval_id}`);navigate("/approvals")}else{alert("Установлено");await workforceItemPage(id)}}catch(error){alert(error.message);install.disabled=false}};actions.append(install);
  if(installation?.status==="ACTIVE"){const remove=node("button","Удалить","secondary");remove.onclick=async()=>{const response=await api(`/api/workforce/${item.id}/uninstall`,{method:"POST",body:JSON.stringify({workspace_id:summary.workspace.id})});alert(`Требуется подтверждение ${response.approval_id}`);navigate("/approvals")};actions.append(remove);const wizard=node("div",undefined,"integration-wizard");wizard.append(node("h3","Подключить интеграцию"));const provider=node("select");["TELEGRAM","EMAIL","GOOGLE","SLACK","GITHUB","WEBHOOK","API_KEY"].forEach(value=>{const option=node("option",value);option.value=value;provider.append(option)});const reference=node("input");reference.placeholder="SECRET_REFERENCE (без значения секрета)";const connect=node("button","Запросить подключение","secondary");connect.onclick=async()=>{connect.disabled=true;try{const response=await api(`/api/workforce/${item.id}/integration`,{method:"POST",body:JSON.stringify({workspace_id:summary.workspace.id,provider:provider.value,secret_reference:reference.value,configuration:{mode:"workspace"}})});alert(`Требуется подтверждение ${response.approval_id}`);navigate("/approvals")}catch(error){alert(error.message);connect.disabled=false}};wizard.append(provider,reference,connect);actions.append(wizard)}
  el("content").append(hero,details,actions);
}

async function aiTeamPage(){
  title("My AI Team");activate("/ai-team");const summary=await api("/api/dashboard");const data=await api(`/api/workforce/team?workspace_id=${encodeURIComponent(summary.workspace.id)}`);clear();
  const hero=card(`AI Team · ${summary.workspace.name}`,true);hero.classList.add("full");hero.append(node("p","Установленные сотрудники изолированы внутри текущего workspace.","muted"));const grid=node("div",undefined,"grid marketplace-v4-grid");(data.items||[]).forEach(item=>{const c=card(item.name);c.append(badge(item.status),badge(item.load),node("p",`Версия ${item.version} · задач ${item.tasks}`,"muted"),node("p",`Успешность ${item.success_rate}% · ошибок ${item.errors}`),node("p",`Memory: ${item.memory} · стоимость ${(item.cost_cents/100).toFixed(2)} USD`,"muted"));grid.append(c)});if(!data.items?.length)grid.append(node("div","Команда пока пуста. Установите сотрудника в Marketplace.","empty"));el("content").append(hero,grid);
}

async function developerPortalPage(){
  title("Developer Portal");activate("/developer");const data=await api("/api/workforce/developer");clear();const overview=card("Creator Analytics",true);overview.classList.add("full");overview.append(node("p","Платежи отключены. Отображаются только расчётные показатели будущей revenue-sharing модели.","muted"));const metrics=node("div",undefined,"metrics operations-metrics");const packages=data.packages||[];const earnings=(data.earnings||[]).reduce((sum,item)=>sum+Number(item.creator_cents||0),0);metrics.append(metric("Packages",packages.length),metric("Commission",`${data.commission_bps/100}%`),metric("Estimated earnings",`${(earnings/100).toFixed(2)} USD`),metric("Payments","OFF"));overview.append(metrics);const list=card("My Packages",true);list.classList.add("full");packages.forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",`${item.name} · v${item.version}`),badge(item.status));list.append(row)});if(!packages.length)list.append(node("div","Создайте профиль автора и опубликуйте первый декларативный пакет.","empty"));el("content").append(overview,list);
}

async function enterpriseScope(){const data=await api("/api/dashboard");return `workspace_id=${encodeURIComponent(data.workspace.id)}`}
async function securityCenterPage(){title("Enterprise Security Center");activate("/security-center");const q=await enterpriseScope();const [data,events]=await Promise.all([api(`/api/enterprise/security-center?${q}`),api(`/api/enterprise/security-events?${q}&limit=20`)]);clear();const overview=card("Security Overview",true);overview.classList.add("full");const values=node("div",undefined,"metrics operations-metrics");values.append(metric("Users",data.users),metric("Policies",data.policies),metric("Active Agents",data.active_agents),metric("Security Events",data.security_events),metric("Risk Level",data.risk_level));overview.append(values);const audit=card("Advanced Audit",true);audit.classList.add("full");(events.items||[]).forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",`${item.action} · ${item.resource}`),badge(item.result),badge(item.risk_level),node("small",fmt(item.created_at),"muted"));audit.append(row)});if(!events.items.length)audit.append(node("div","No enterprise security events","empty"));audit.append(node("p",`Hash chain: ${events.chain_valid?"VALID":"INVALID"}`,events.chain_valid?"muted":"danger"));el("content").append(overview,audit)}
async function policiesPage(){title("Enterprise Policies");activate("/policies");const q=await enterpriseScope();const data=await api(`/api/enterprise/policies?${q}`);clear();const c=card("Policy Management",true);c.classList.add("full");(data.items||[]).forEach(item=>{const row=node("div",undefined,"approval-row");const info=node("div");info.append(node("strong",item.name),node("p",`${item.type} · version ${item.current_version}`,"muted"));row.append(info,badge(item.status));c.append(row)});if(!data.items.length)c.append(node("div","No organization policies. Changes require owner approval.","empty"));c.append(node("p","Policy changes are versioned and cannot be applied from this read-only view.","muted"));el("content").append(c)}
async function slaPage(){title("SLA Monitoring");activate("/sla");const q=await enterpriseScope();const data=await api(`/api/enterprise/sla?${q}`);clear();const c=card("SLA",true);c.classList.add("full");const values=node("div",undefined,"metrics operations-metrics");values.append(metric("Availability",`${data.availability}%`),metric("Task Success",`${data.task_success_rate}%`),metric("Average",`${data.average_response_seconds} sec`),metric("Error Rate",`${data.error_rate}%`),metric("Tasks",data.total_tasks));c.append(values);el("content").append(c)}
async function storageHealthPage(){title("Storage Observability");activate("/storage-health");const q=await enterpriseScope();const data=await api(`/api/enterprise/storage-health?${q}`);clear();const c=card("Storage Health",true);c.classList.add("full");[["Database",data.database],["Permissions",data.permissions],["Backup",data.backup],["Disk",`${data.disk_percent}%`],["Overall",data.status]].forEach(([label,value])=>{const row=node("div",undefined,"health-row");row.append(node("span",label),badge(value));c.append(row)});el("content").append(c)}
async function enterprisePage(){title("Enterprise Operations");activate("/enterprise");const q=await enterpriseScope();const [profiles,sso,compliance]=await Promise.all([api(`/api/enterprise/deployment-profiles?${q}`),api(`/api/enterprise/sso?${q}`),api(`/api/enterprise/compliance?${q}`)]);clear();const identity=card("Identity Foundation");identity.append(node("p",`External provider configured: ${sso.configured?"YES":"NO"}`,"muted"));sso.providers.forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",item.type),badge(item.enabled?"ENABLED":"DISABLED"));identity.append(row)});const deployment=card("Deployment Profiles",true);(profiles.items||[]).forEach(item=>{const row=node("div",undefined,"health-row");row.append(node("span",item.name),badge(item.status));deployment.append(row)});const controls=card("Compliance Foundation",true);Object.entries(compliance.controls||{}).forEach(([key,value])=>{const row=node("div",undefined,"health-row");row.append(node("span",key.replaceAll("_"," ")),badge(value?"PASS":"FAIL"));controls.append(row)});controls.append(node("p","Foundation only; no certification is claimed.","muted"));const grid=node("div",undefined,"grid");grid.append(identity,deployment,controls);el("content").append(grid)}

const routeV34=route;
route=async function(){const path=location.pathname;state.realtimeCallback=null;try{if(path==="/marketplace")return await workforceMarketplacePage("EMPLOYEE");if(path==="/marketplace/workflows")return await workforceMarketplacePage("WORKFLOW");if(path==="/marketplace/skills")return await workforceMarketplacePage("SKILL");if(path.startsWith("/marketplace/item/"))return await workforceItemPage(decodeURIComponent(path.slice(18)));if(path==="/ai-team")return await aiTeamPage();if(path==="/developer")return await developerPortalPage();if(path==="/workbench")return await workbenchPage();if(path.startsWith("/workbench/tasks/"))return await workbenchTaskPage(decodeURIComponent(path.slice(17)));if(path==="/home")return await homePage();if(path==="/activity")return await activityPage();if(path==="/notifications")return await notificationsPage();if(path==="/workspace")return await workspaceOverviewPage();if(path==="/agents/status")return await agentStatusPage();if(path==="/analytics")return await operationsAnalyticsPage();if(path==="/onboarding")return await onboardingPage();if(path==="/security-center")return await securityCenterPage();if(path==="/policies")return await policiesPage();if(path==="/sla")return await slaPage();if(path==="/storage-health")return await storageHealthPage();if(path==="/enterprise")return await enterprisePage();return await routeV34()}catch(error){if(error.message!=="UNAUTHORIZED")errorView(error)}};

function navigate(path){history.pushState({},"",path);route()}
document.addEventListener("click",event=>{const link=event.target.closest("a[data-route]");if(link){event.preventDefault();navigate(link.getAttribute("href"))}});window.addEventListener("popstate",route);
document.querySelectorAll("[data-menu-tab]").forEach(button=>button.addEventListener("click",()=>selectMenuTab(button.dataset.menuTab)));
try{selectMenuTab(sessionStorage.getItem("nexora-menu-tab")||"work",false)}catch{selectMenuTab("work",false)}
el("notification-toggle").onclick=async()=>{const tray=el("notification-tray");const opening=tray.classList.contains("hidden");tray.classList.toggle("hidden",!opening);el("notification-toggle").setAttribute("aria-expanded",String(opening));if(opening)await refreshNotificationCenter(true)};
el("notification-close").onclick=closeNotificationTray;
el("notification-all").onclick=()=>{closeNotificationTray();navigate("/notifications")};
el("command-toggle").onclick=openCommandPalette;
el("command-close").onclick=closeCommandPalette;
el("command-modal").onclick=event=>{if(event.target===el("command-modal"))closeCommandPalette()};
el("command-input").oninput=event=>renderCommandPalette(event.target.value);
el("command-input").onkeydown=event=>{if(event.key==="Enter"){event.preventDefault();const first=el("command-results").querySelector(".command-item");if(first)first.click()}};
el("quick-task-toggle").onclick=openQuickTask;
el("quick-task-cancel").onclick=closeQuickTask;
el("quick-task-modal").onclick=event=>{if(event.target===el("quick-task-modal"))closeQuickTask()};
el("quick-task-form").onsubmit=async event=>{
  event.preventDefault();
  const message=el("quick-task-message").value.trim();
  if(!message||!state.notificationWorkspace)return;
  const submit=el("quick-task-submit");submit.disabled=true;submit.textContent="Создаём задачу…";el("quick-task-error").textContent="";
  try{
    const result=await api("/api/workbench/tasks",{method:"POST",body:JSON.stringify({message,workspace_id:state.notificationWorkspace,idempotency_key:requestKey("quick-task")})});
    closeQuickTask();navigate(`/workbench/tasks/${encodeURIComponent(result.task_id||result.id)}`);
  }catch(error){
    submit.disabled=false;submit.textContent="Запустить агентов";el("quick-task-error").textContent=error.message;
  }
};
document.addEventListener("keydown",event=>{
  if((event.ctrlKey||event.metaKey)&&event.key.toLocaleLowerCase()==="k"&&!el("app").classList.contains("hidden")){event.preventDefault();openCommandPalette();return}
  if(event.key==="Escape"){
    if(!el("command-modal").classList.contains("hidden"))closeCommandPalette();
    else if(!el("quick-task-modal").classList.contains("hidden"))closeQuickTask();
  }
});
document.addEventListener("click",event=>{if(!event.target.closest(".header-actions"))closeNotificationTray()});
el("login-form").addEventListener("submit",async event=>{event.preventDefault();el("login-error").textContent="";const data=Object.fromEntries(new FormData(event.target));try{const result=await api("/api/login",{method:"POST",body:JSON.stringify(data)});state.csrf=result.csrf_token;event.target.reset();showApp();await initializeNotificationCenter();route()}catch(error){el("login-error").textContent=error.message==="UNAUTHORIZED"?"Неверные данные или доступ временно ограничен.":error.message}});
el("logout").onclick=async()=>{try{await api("/api/logout",{method:"POST",body:"{}"})}finally{showLogin()}};
(async()=>{try{const session=await api("/api/session");state.csrf=session.csrf_token;showApp();await initializeNotificationCenter();route()}catch{showLogin()}})();
