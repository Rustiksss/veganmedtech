'use strict';
// Browser UI: accounts and reports use the server; labelled demonstrations remain local.
const icons = {
    compass: '<path d="m20 4-4 12-12 4L8 8l12-4Z"/><path d="m8 8 8 8"/><circle cx="12" cy="12" r="10"/>',
    home: '<path d="m3 10 9-7 9 7v10H3V10Z"/><path d="M9 20v-7h6v7"/>',
    edit: '<path d="m16 3 5 5-12 12H4v-5L16 3Z"/><path d="m13 6 5 5M4 21h17"/>',
    history: '<rect x="5" y="4" width="14" height="17" rx="3"/><path d="M9 2v4m6-4v4M9 11h6m-6 4h5"/>',
    people: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m2-16a3 3 0 0 1 0 6m2 3a5 5 0 0 1 2 4v3"/>',
    arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    back: '<path d="M19 12H5m5-5-5 5 5 5"/>',
    leaf: '<path d="M20 4C8 2 2 8 6 16s16 3 14-12Z"/><path d="M4 21 15 10"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    chat: '<path d="M21 11a9 8 0 0 1-9 8H7l-4 3v-6a8 8 0 1 1 18-5Z"/><path d="M8 10h8m-8 4h5"/>',
    bell: '<path d="M5 16V9a7 7 0 0 1 14 0v7l2 2H3l2-2Zm4 5h6"/>',
    pill: '<path d="m4 12 8-8a6 6 0 0 1 8 8l-8 8a6 6 0 0 1-8-8Zm4-4 8 8"/>',
    game: '<rect x="3" y="6" width="18" height="14" rx="4"/><path d="M7 10v6m-3-3h6m5-2h.01m3 4h.01M9 6V3h6"/>',
    film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16m10-16v16M3 9h4m-4 6h4m10-6h4m-4 6h4"/>',
    sound: '<path d="M4 10v4h4l5 5V5l-5 5H4Zm13-3a7 7 0 0 1 0 10m3-13a11 11 0 0 1 0 16"/>',
    sparkle: '<path d="m12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3 3-6Z"/>',
    external: '<path d="M14 3h7v7m0-7L10 14m-1-9H4v16h16v-5"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.info}</svg>`;
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
} [c]));
let people = [];
const doctors = [{
    id: 'doctor-a',
    name: 'Анна Л.',
    initials: 'АЛ',
    online: true,
    description: 'Психиатр · учебный профиль',
    about: 'Вымышленный профиль для знакомства с кабинетом и перепиской.'
}, {
    id: 'doctor-b',
    name: 'Илья М.',
    initials: 'ИМ',
    online: false,
    description: 'Психиатр',
    about: 'Учебный профиль специалиста. Переписка не предоставляет доступ к вашей истории.'
}, {
    id: 'doctor-c',
    name: 'Мария С.',
    initials: 'МС',
    online: true,
    description: 'Психиатр',
    about: 'Пример знакомства со специалистом перед обращением.'
}];
const localDateTime = () => {
    const d = new Date();
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const dateKey = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const todayKey = dateKey(new Date());
const state = {
    reports: [],
    nextId: 3,
    draft: {
        date: localDateTime(),
        text: ''
    },
    errors: {},
    pending: false,
    saveError: false,
    saveMessage: '',
    saved: false,
    profiles: {
        patient: 'Александра К.',
        doctor: 'Анна Л.'
    },
    registration: {
        patient: '',
        doctor: ''
    },
    registrationError: '',
    mood: '',
    questionnaires: {},
    read: new Set(),
    taken: new Set(),
    selectedDay: todayKey,
    month: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
    messages: {
        'patient-a:doctor-a': [{
            from: 'doctor',
            text: 'Это пример диалога с ведущим врачом. Здесь можно подготовить вопросы к встрече.',
            time: 'Учебное сообщение'
        }]
    },
    chatDrafts: {},
    chatError: '',
    chatPending: false,
    assistant: {mode: 'off', items: [], cursor: null, draft: '', pending: false, error: '', key: null, sentText: ''},
    assistantAlerts: {mode: 'off', items: [], cursor: null, error: ''},
    breathSeconds: 0,
    breathRunning: false,
    volume: 35,
    audioStatus: 'stopped',
    audioError: ''
};
const reportsFor = id => state.reports.filter(r => r.patientId === id).sort((a, b) => b.observedAt.localeCompare(a.observedAt) || b.id - a.id);
const prettyDate = value => new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit'
}).format(new Date(value));
const reportCount = n => `${n} ${{one:'запись',few:'записи',many:'записей',other:'записи'}[new Intl.PluralRules('ru').select(n)]}`;
const avatar = p => `<span class="avatar ${p.tint||''}" aria-hidden="true">${escapeHtml(p.initials)}</span>`;
const announce = text => {
    document.querySelector('#announcer').textContent = text;
};
const linkButton = (label, href, style = '') => `<a href="${href}" class="btn ${style}">${label}</a>`;
const external = (text, url) => `<a class="text-link" href="${url}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">${text} ${icon('external')}</a>`;

function heading(title, subtitle = '', action = '') {
    return `<div class="page-heading"><div><h1 id="pageTitle" tabindex="-1">${title}</h1>${subtitle?`<p>${subtitle}</p>`:''}</div>${action}</div>`;
}
const patientItems = [
    ['home', 'home', 'Главная', '/patient'],
    ['assistant', 'sparkle', 'Ассистент', '/patient/assistant'],
    ['questionnaires', 'edit', 'Опросники', '/patient/questionnaires'],
    ['notifications', 'bell', 'Уведомления', '/patient/notifications'],
    ['doctors', 'chat', 'Связаться с доктором', '/patient/doctors'],
    ['medication', 'pill', 'Календарь приёма', '/patient/medication'],
    ['games', 'game', 'Мини-игры', '/patient/games'],
    ['films', 'film', 'Кино для вечера', '/patient/films'],
    ['sounds', 'sound', 'Звуки', '/patient/sounds'],
    ['report', 'edit', 'Новая запись', '/patient/report'],
    ['history', 'history', 'История наблюдений', '/patient/history']
];
const doctorItems = [
    ['patients', 'people', 'Мои пациенты', '/doctor'],
    ['assistant-alerts', 'bell', 'Уведомления ассистента', '/doctor/assistant-alerts'],
    ['interactions', 'pill', 'Совместимость лекарств', '/doctor/interactions']
];

function decodeAuthKey(value) { try { return decodeURIComponent(value); } catch { return ''; } }
function readRoute() {
    const p = location.hash.slice(1) || '/';
    if (p === '/') return {
        view: 'welcome'
    };
    if (p === '/login') return {
        view: 'login'
    };
    if (p === '/password/request') return {
        view: 'password-request'
    };
    if (p === '/password/change') return {
        view: 'password-change',
        role: sessionUser?.role
    };
    const verify = /^\/verify-email\/(.+)$/.exec(p);
    if (verify) return {
        view: 'verify-email',
        key: decodeAuthKey(verify[1])
    };
    const reset = /^\/password\/reset\/(.+)$/.exec(p);
    if (reset) return {
        view: 'password-reset',
        key: decodeAuthKey(reset[1])
    };
    const reg = /^\/register\/(patient|doctor)$/.exec(p);
    if (reg) return {
        view: 'register',
        role: reg[1]
    };
    for (const [view, , , path] of patientItems)
        if (p === path) return {
            role: 'patient',
            view
        };
    const questionnaire = /^\/patient\/questionnaires\/([a-z0-9-]+)$/.exec(p);
    if (questionnaire) return {
        role: 'patient',
        view: 'questionnaires',
        questionnaireId: questionnaire[1]
    };
    if (p === '/doctor') return {
        role: 'doctor',
        view: 'patients'
    };
    if (p === '/doctor/assistant-alerts') return {role: 'doctor', view: 'assistant-alerts'};
    if (p === '/doctor/interactions') return {
        role: 'doctor',
        view: 'interactions'
    };
    const detail = /^\/doctor\/patients\/(\d+)$/.exec(p);
    if (detail) return {
        role: 'doctor',
        view: 'detail',
        patientId: Number(detail[1])
    };
    const dc = /^\/doctor\/chat\/(\d+)$/.exec(p);
    if (dc) return {
        role: 'doctor',
        view: 'chat',
        patientId: Number(dc[1]),
        doctorId: 'doctor-a'
    };
    const pc = /^\/patient\/chat\/(doctor-[abc])$/.exec(p);
    if (pc) return {
        role: 'patient',
        view: 'chat',
        patientId: 'patient-a',
        doctorId: pc[1]
    };
    return {
        role: p.startsWith('/doctor') ? 'doctor' : 'patient',
        view: 'missing'
    };
}

function brand(href = '#/') {
    return `<a class="brand" href="${href}"><span class="brand-mark">${icon('compass')}</span><span><strong>VeganMedTech</strong><small>Клинический компас</small></span></a>`;
}

function notifications() {
    return [{
        id: 'medication',
        title: !hasIntake(todayKey) ? 'Сегодня без учебных приёмов' : state.taken.has(todayKey) ? 'Приём отмечен' : 'Время учебного приёма',
        text: !hasIntake(todayKey) ? 'На сегодня в учебном календаре нет приёмов.' : state.taken.has(todayKey) ? 'Вы отметили «Принял» в календаре на сегодня.' : '09:00 · Учебный препарат. Сверьтесь с учебным расписанием.',
        href: '/patient/medication',
        action: 'Открыть календарь',
        done: !hasIntake(todayKey) || state.taken.has(todayKey)
    }, {
        id: 'visit',
        title: 'Запланирована встреча',
        text: 'Пример: сегодня в 16:00 — встреча с ведущим психиатром. Это учебное событие.',
        href: '/patient/chat/doctor-a',
        action: 'Подготовить вопрос'
    }, {
        id: 'report',
        title: 'Небольшая пауза для себя',
        text: 'Если хотите, запишите, как прошёл день и что вы заметили в своём самочувствии.',
        href: '/patient/report',
        action: 'Добавить наблюдение'
    }];
}
const unread = () => notifications().filter(n => !n.done && !state.read.has(n.id)).length;

function navLinks(route) {
    return (route.role === 'doctor' ? doctorItems : patientItems).map(([view, name, label, path]) => {
        const active = route.view === view || (view === 'patients' && ['detail', 'chat'].includes(route.view)) || (view === 'doctors' && route.view === 'chat');
        return `<a class="nav-link" href="#${path}" ${active?'aria-current="page"':''}>${icon(name)}<span>${label}</span>${view==='notifications'&&unread()?`<span class="nav-count" aria-label="Непрочитанных: ${unread()}">${unread()}</span>`:''}</a>`;
    }).join('');
}

function welcome() {
    return `${heading('Ваше пространство<br>для заботы о себе','Наблюдения пациента и рабочее пространство врача.')}<h2>Создайте аккаунт</h2><div class="role-grid"><a class="surface role-card" href="#/register/patient"><h2>Я пациент</h2><p>Сохраняйте собственные наблюдения.</p><span class="text-link">Зарегистрироваться</span></a><a class="surface role-card" href="#/register/doctor"><h2>Я врач</h2><p>Подайте заявку на врачебный доступ.</p><span class="text-link">Подать заявку</span></a></div><p class="auth-links"><a class="btn outline" href="#/login">Уже есть аккаунт — войти</a></p><p class="subtle">Локальная тестовая среда. Используйте вымышленные данные.</p>`;
}

function registration(route) {
    return accountForm('signup', route);
}

function patientHome() {
    return `${heading(`Здравствуйте, ${escapeHtml(state.profiles.patient)}!`,'Небольшие наблюдения и привычные дела — шаг за шагом.',linkButton(`${icon('bell')} Уведомления · ${unread()}`,'#/patient/notifications','outline'))}<div class="overview-grid"><section class="hero"><div class="eyebrow">${icon('sparkle')} Ваш цифровой ассистент</div><h2>Как проходит<br>ваш день?</h2><p>${state.mood?`Вы описали настроение как «${escapeHtml(state.mood.toLowerCase())}». Можно добавить наблюдение своими словами.`:'Остановитесь на минуту, чтобы прислушаться к себе и записать важное.'}</p>${linkButton(`Отметить настроение ${icon('arrow')}`,'#/patient/assistant')}</section><section class="surface doctor-card"><span class="card-label">Ваш ведущий врач</span><div class="doctor-profile">${avatar(doctors[0])}<div><strong>${escapeHtml(sessionUser?.leading_doctor?.name||'Пока не назначен')}</strong><small>Связь устанавливает оператор</small></div></div>${linkButton('Учебные чаты','#/patient/doctors','soft')}</section></div><div class="tile-grid" style="margin-top:22px"><section class="surface tile"><span class="pill">${icon('pill')} Сегодня</span><h2>${state.taken.has(todayKey)?'Приём отмечен':'Учебный календарь'}</h2><p>${state.taken.has(todayKey)?'Ваша отметка сохранена до перезагрузки.':hasIntake(todayKey)?'09:00 · Учебный препарат. Отметьте приём в календаре.':'На сегодня учебных приёмов нет.'}</p>${linkButton('Открыть календарь','#/patient/medication','outline small')}</section><section class="surface tile"><span class="pill">${icon('leaf')} Время для себя</span><h2>Небольшая передышка</h2><p>Дыхание по квадрату, океанские волны или кино на вечер — выбирайте то, что вам по душе.</p><div class="actions">${linkButton('Мини-игры','#/patient/games','soft small')}${linkButton('Звуки','#/patient/sounds','outline small')}</div></section></div><section><div class="section-heading"><h2>Последние наблюдения</h2><a class="text-link" href="#/patient/history">Вся история ${icon('arrow')}</a></div><div class="recent-grid">${reportCards(selfId(),true)}</div></section>`;
}

function assistantOverview() {
    return `${heading('Как вы себя чувствуете?','Ваш цифровой ассистент поможет сохранить наблюдения и не потерять важные дела.')}<div class="content-grid"><div class="stack"><section class="surface tile"><span class="eyebrow">${icon('sparkle')} Небольшая проверка самочувствия</span><h2>Как бы вы описали настроение?</h2><p>Выберите близкое вам слово. Это ваша самооценка, без баллов и диагноза.</p><div class="moods">${['Непростое','Нейтральное','Спокойное','Приподнятое'].map(x=>`<button class="btn outline small" data-mood="${x}" aria-pressed="${state.mood===x}">${x}</button>`).join('')}</div><p id="moodStatus" class="subtle" role="status">${state.mood?`Вы отметили: ${escapeHtml(state.mood)}. Эта отметка сохранена в текущей вкладке.`:'Можно выбрать позже — здесь нет обязательных ответов.'}</p>${linkButton('Записать самочувствие','#/patient/report','soft')}</section><section class="surface tile"><span class="eyebrow">${icon('edit')} В своём темпе</span><h2>Опросники о себе</h2><p>Удовлетворённость жизнью, восприятие болезни, отношения и самоотношение. Выберите методику и получите расчёт по своим ответам.</p>${linkButton('Выбрать опросник '+icon('arrow'),'#/patient/questionnaires','outline small')}</section></div><aside class="aside-card"><div class="hero-icon">${icon('bell')}</div><h2>Ваши напоминания</h2><p>${state.taken.has(todayKey)?'Учебный приём на сегодня отмечен.':hasIntake(todayKey)?'Пример: учебный приём в 09:00.':'Сегодня учебных приёмов нет.'}<br>Пример: встреча с психиатром сегодня в 16:00.</p><a class="text-link" href="#/patient/notifications">Все уведомления ${icon('arrow')}</a><p>Ассистент не оценивает диагноз и не меняет план врача.</p></aside></div>`;
}

function assistant() {
    const box = state.assistant;
    return `${heading('ИИ-ассистент','Можно задать вопрос о сервисе или рассказать, как проходит день.')}<p class="notice assistant-boundary">Это ИИ, а не врач. Переписка сохраняется на сервере и обрабатывается внешним сервисом Polza AI. Используйте только вымышленные сведения.<br><strong>${box.mode==='demo'?'Включён демонстрационный анализ вымышленных сообщений. При возможном сигнале сообщение и основание будут доступны текущему ведущему врачу.':'Автоматическая проверка опасных мыслей и уведомление врача пока отключены.'}</strong>${box.mode==='demo'?'<br>Это не оценка риска: возможны пропуски и ошибки. Нет гарантии прочтения или экстренной реакции врача.':''}</p>
    <section class="surface chat assistant-chat" aria-label="Диалог с ИИ-ассистентом">
    ${box.cursor?'<button class="btn outline small" data-assistant-more>Загрузить предыдущие сообщения</button>':''}
    <div class="chat-thread" tabindex="0" aria-label="История диалога с ИИ">${box.items.length?box.items.slice().sort((a,b)=>a.id-b.id).map(m=>`<article class="message mine"><small>Вы · ${prettyDate(m.created_at)}</small><p>${escapeHtml(m.text)}</p>${assistantAnalysis(m)}</article>${m.status==='completed'?`<article class="message"><small>ИИ-ассистент</small><p>${escapeHtml(m.reply)}</p></article>`:`<article class="message"><small>ИИ-ассистент</small><p>${m.status==='pending'?'Готовим ответ…':escapeHtml(m.error||'Ответ не получен.')}</p>${m.status!=='pending'?`<button class="btn outline small" data-assistant-retry="${m.id}">Повторить сообщение</button>`:''}</article>`}`).join(''):'<p class="subtle">Пока нет сообщений. Например: «Как сохранить наблюдение?»</p>'}</div>
    <form id="assistantForm" class="chat-form" novalidate aria-busy="${box.pending}">
    <label for="assistantText">Ваше сообщение</label><textarea id="assistantText" rows="3" required aria-describedby="assistantHelp${box.error?' assistantError':''}" aria-invalid="${!!box.error}" ${box.pending?'disabled':''}>${escapeHtml(box.draft)}</textarea>
    <p id="assistantHelp" class="field-help">От 1 до 2000 символов. Для подсказок по сервису и поддерживающей беседы.</p>
    ${box.error?`<p id="assistantError" class="field-error" role="alert">${escapeHtml(box.error)}</p>`:''}
    <p role="status" id="assistantStatus">${box.pending?'Ожидаем ответ ИИ…':''}</p>
    <button class="btn" type="submit" ${box.pending?'disabled':''}>${box.pending?'Отправляем…':box.key?'Проверить отправку и повторить':'Отправить'} ${icon('arrow')}</button></form></section>
    <div class="assistant-extras">${assistantOverview().replace(/<h1 id="pageTitle" tabindex="-1">(.*?)<\/h1>/, '<h2>$1</h2>')}</div>`;
}
function assistantAnalysis(message) {
    const labels = {matched:'Демоанализ: найден возможный сигнал.', uncertain:'Демоанализ: неоднозначное упоминание, требуется просмотр.',
        no_match:'Демоанализ: совпадений не найдено. Это не подтверждает отсутствие риска.', failed:'Демоанализ: проверка не выполнена.',
        not_evaluated:message.turn_alerting_mode==='demo'?'Демоанализ ещё не выполнен.':'Анализ для этого сообщения не выполнялся.'};
    const delivery = {available:'Событие сохранено и доступно текущему ведущему врачу. Это не подтверждает прочтение.',
        no_doctor:'Событие сохранено. Действующий ведущий врач не назначен; доставка не подтверждена.'};
    return `<p class="field-help analysis-status">${escapeHtml(labels[message.analysis_status]||labels.not_evaluated)}${delivery[message.notification_status]?'<br>'+escapeHtml(delivery[message.notification_status]):''}</p>`;
}
function assistantAlertsPage() {
    const box = state.assistantAlerts;
    return `${heading('Уведомления ассистента',box.mode==='demo'?'Демонстрационный анализ вымышленных сообщений включён. Возможные сигналы требуют проверки врачом.':'Автоматическое распознавание отключено. Сохранённые демонстрационные события доступны для просмотра.')}
    <p class="subtle">Это не клиническая оценка риска. События сохраняются до входа в кабинет; прочтение и экстренная реакция не гарантируются. Просмотр не подтверждает клиническое действие.</p>
    <div id="assistantAlerts" class="stack">${box.error?`<p class="notice error" role="alert">${escapeHtml(box.error)}</p><button class="btn outline" data-alert-refresh>Повторить загрузку</button>`:box.items.length?box.items.map(n=>`<article class="surface tile"><span class="pill">${n.analysis?.length?'Демонстрационный сигнал — требуется проверка врачом':'Синтетическое событие · проверка доставки'}</span><h2>${escapeHtml(n.patient_name)}</h2><time>${prettyDate(n.created_at)}</time><p class="alert-text">${escapeHtml(n.text)}</p>${n.analysis_status==='uncertain'?'<p><strong>Неоднозначно — требуется просмотр.</strong></p>':''}${n.analysis?.length?`<ul>${n.analysis.map(a=>`<li><strong>${escapeHtml(a.label)}</strong> · ${escapeHtml(a.time_label)}<blockquote class="alert-text">${escapeHtml(a.quote)}</blockquote><small>Основание: ${escapeHtml(a.source_ref)}</small></li>`).join('')}</ul>`:''}<p>Версия: ${escapeHtml(n.policy_version)}</p>${n.seen_at?'<p class="read">Вы отметили просмотр</p>':`<button class="btn outline small" data-alert-seen="${n.id}">Отметить просмотр</button>`}</article>`).join(''):'<div class="surface empty"><h2>Уведомлений пока нет</h2><p>Отсутствие уведомлений не подтверждает отсутствие риска.</p></div>'}</div>${box.cursor?'<button class="btn outline" data-alert-more>Загрузить ещё</button>':''}`;
}
let assistantTimer = null, alertTimer = null;
function stopAssistantPolling() { clearTimeout(assistantTimer); clearInterval(alertTimer); assistantTimer = alertTimer = null; }
function mergeTurns(items) {
    const box = state.assistant;
    const map = new Map(box.items.map(m=>[m.id,m]));
    items.forEach(m=>map.set(m.id,m)); box.items = [...map.values()];
}
function scheduleAssistantPolling() {
    clearTimeout(assistantTimer);
    if (loading || document.hidden || readRoute().view!=='assistant' || sessionUser?.role!=='patient') return;
    const pending = state.assistant.items.filter(m=>m.status==='pending');
    if (!pending.length) return;
    const box = state.assistant, ticket = routeToken;
    assistantTimer = setTimeout(async()=>{
        try {
            const data = await CompassAPI.request('/api/me/assistant/messages/'+pending[0].id);
            if (box!==state.assistant || ticket!==routeToken || readRoute().view!=='assistant') return;
            box.mode=data.alerting_mode||'off';mergeTurns([data]); box.pending = data.status==='pending';
            render(); scheduleAssistantPolling();
        } catch(error) {
            if (box!==state.assistant || ticket!==routeToken || error.name==='AbortError') return;
            box.pending = false; box.error = 'Не удалось проверить отправку. Обновите раздел.';
            if ([401,403].includes(error.status)) { box.items=[]; applyUser(null); }
            render();
        }
    },1500);
}
async function sendAssistant(event) {
    event?.preventDefault();
    const box = state.assistant, ticket = routeToken;
    if (box.pending) return;
    const text = box.draft.trim();
    if (!text || text.length>2000) {box.error='Напишите от 1 до 2000 символов.';render();document.querySelector('#assistantText')?.focus();return;}
    if (box.sentText!==text || !box.key) { box.key=crypto.randomUUID(); box.sentText=text; }
    box.pending=true;box.error='';render();
    try {
        const data = await CompassAPI.request('/api/me/assistant/messages',{method:'POST',body:{text},headers:{'Idempotency-Key':box.key}});
        if (box!==state.assistant || ticket!==routeToken) return;
        box.mode=data.alerting_mode||'off';mergeTurns([data]); box.pending=data.status==='pending';
        if (data.status==='completed') {box.draft='';box.key=null;box.sentText='';announce('Ответ ИИ получен.');}
        else if (data.status!=='pending') {box.error=data.error;box.key=null;}
    } catch(error) {
        if (box!==state.assistant || ticket!==routeToken || error.name==='AbortError') return;
        box.pending=false;
        box.error=[401,403].includes(error.status)?'Сессия завершена. Войдите снова.':error.status===409?'Конфликт отправки. Обновите историю.':'Не удалось получить ответ. Текст сохранён; проверьте отправку повторным нажатием.';
        if ([401,403].includes(error.status)) {box.items=[];applyUser(null);}
    }
    if (readRoute().view==='assistant') {render();document.querySelector('#assistantText')?.focus();scheduleAssistantPolling();}
}
async function moreAssistant(button) {
    const box=state.assistant, ticket=routeToken;
    if (!box.cursor) return;
    button.disabled=true;
    try { const data=await CompassAPI.request('/api/me/assistant/messages?cursor='+encodeURIComponent(box.cursor));
        if(box!==state.assistant||ticket!==routeToken)return;
        box.mode=data.alerting_mode||'off';mergeTurns(data.results);box.cursor=data.next_cursor;render();
    } catch(error) {if(box!==state.assistant||ticket!==routeToken||error.name==='AbortError')return;box.error='Не удалось загрузить историю. Повторите попытку.';if([401,403].includes(error.status)){box.items=[];applyUser(null);}render();}
}
async function refreshAssistantAlerts(more=false) {
    const box=state.assistantAlerts, ticket=routeToken;
    if(loading||sessionUser?.role!=='doctor'||!sessionUser.doctor_approved)return;
    try {
        const data=await CompassAPI.request('/api/doctor/assistant-notifications'+(more&&box.cursor?'?cursor='+encodeURIComponent(box.cursor):''));
        if(box!==state.assistantAlerts||ticket!==routeToken)return;
        box.items=more?[...box.items,...data.results.filter(x=>!box.items.some(n=>n.id===x.id))]:data.results;
        box.mode=data.alerting_mode||'off';box.cursor=data.next_cursor;box.error='';
        if(readRoute().view==='assistant-alerts') {
            const focused=document.activeElement?.dataset.alertSeen;
            const scroll=window.scrollY;render();window.scrollTo(0,scroll);
            if(focused)document.querySelector(`[data-alert-seen="${focused}"]`)?.focus({preventScroll:true});
        }
    }catch(error){
        if(box!==state.assistantAlerts||ticket!==routeToken||error.name==='AbortError')return;
        box.items=[];box.cursor=null;box.error='Не удалось проверить уведомления. Повторите загрузку.';
        if([401,403].includes(error.status)){applyUser(null);stopAssistantPolling();}
        if(readRoute().view==='assistant-alerts')render();
    }
}
function startAlertPolling() {
    clearInterval(alertTimer);
    if(loading||sessionUser?.role!=='doctor'||!sessionUser.doctor_approved||document.hidden||publicViews.has(readRoute().view))return;
    alertTimer=setInterval(()=>refreshAssistantAlerts(),15000);
}
async function markAssistantAlert(id) {
    const box=state.assistantAlerts,ticket=routeToken;
    try {await CompassAPI.request('/api/doctor/assistant-notifications/'+id,{method:'POST',body:{}});
        if(box!==state.assistantAlerts||ticket!==routeToken)return;
        await refreshAssistantAlerts();announce('Просмотр отмечен.');document.querySelector('#pageTitle')?.focus();
    } catch(error) {if(box!==state.assistantAlerts||ticket!==routeToken||error.name==='AbortError')return;box.items=[];box.error='Событие недоступно или просмотр не сохранён. Обновите список.';render();}
}
document.addEventListener('visibilitychange',()=>{stopAssistantPolling();if(!document.hidden){startAlertPolling();scheduleAssistantPolling();if(sessionUser?.role==='doctor')refreshAssistantAlerts();}});

function notificationPage() {
    return `${heading('Уведомления','Учебные напоминания о привычных делах и запланированной встрече.')}<p class="subtle" role="status">Непрочитанных: ${unread()}</p><div class="stack">${notifications().map(n=>`<article class="surface notification"><span class="hero-icon">${icon(n.id==='medication'?'pill':n.id==='visit'?'people':'edit')}</span><div class="notification-body"><h2>${n.title}</h2><p>${n.text}</p><div class="actions">${linkButton(n.action,'#'+n.href,'soft small')}${n.done||state.read.has(n.id)?`<span class="read">${n.done?'Выполнено по вашей отметке':'Прочитано'}</span>`:`<button class="btn outline small" data-read="${n.id}">Отметить прочитанным</button>`}</div></div></article>`).join('')}</div>`;
}

function doctorDirectory() {
    return `${heading('Связаться с доктором','Выберите собеседника и подготовьте вопросы. Все профили и статусы в этой демонстрации вымышлены.')}<div class="tile-grid">${doctors.map(d=>`<article class="surface tile"><div class="person">${avatar(d)}<div><strong>${d.name}</strong><small>${d.description}</small></div></div><p style="margin-top:18px"><span class="pill ${d.online?'':'offline'}"><span class="status-dot"></span>${d.online?'В сети':'Не в сети'} · пример</span></p><p>${d.about}</p>${linkButton('Открыть чат '+icon('arrow'),'#/patient/chat/'+d.id,'soft small')}</article>`).join('')}</div><p class="subtle" style="margin-top:20px">Выбор собеседника не меняет вашего ведущего врача. Сообщения остаются в этой вкладке и не отправляются специалистам.</p>`;
}
const chatKey = route => route.patientId + ':' + route.doctorId;

function chatPage(route) {
    const key = chatKey(route),
        doctor = route.role === 'doctor',
        person = doctor ? people.find(p => p.id === route.patientId) : doctors.find(d => d.id === route.doctorId),
        draft = state.chatDrafts[key] || '';
    return `<a class="back" href="${doctor?'#/doctor/patients/'+route.patientId:'#/patient/doctors'}">${icon('back')} ${doctor?'К карточке пациента':'К специалистам'}</a>${heading(`Чат · ${escapeHtml(person.name)}`,'Демонстрационная переписка. Сообщения видны только в текущей вкладке.')}<section class="surface chat"><div class="chat-thread" aria-label="История сообщений">${(state.messages[key]||[]).length?(state.messages[key]||[]).map(m=>`<article class="message ${m.from===route.role?'mine':''}"><small>${m.from==='doctor'?'Врач':'Пациент'}</small><p>${escapeHtml(m.text)}</p><small>${escapeHtml(m.time)} · ${m.time==='Учебное сообщение'?'пример':'добавлено в этой вкладке'}</small></article>`).join(''):'<p class="subtle">Пока нет сообщений. Начните с вопроса, который хотите обсудить.</p>'}</div><form id="chatForm" class="chat-form" novalidate aria-busy="${state.chatPending}"><label for="chatText">Сообщение</label><textarea id="chatText" name="message" required aria-invalid="${!!state.chatError}" aria-describedby="chatHelp${state.chatError?' chatError':''}" ${state.chatPending?'disabled':''}>${escapeHtml(draft)}</textarea><p id="chatHelp" class="field-help">От 1 до 2000 символов. Не вводите реальные медицинские данные.</p>${state.chatError?`<p id="chatError" class="field-error" role="alert">${state.chatError}</p>`:''}<button class="btn" type="submit" ${state.chatPending?'disabled':''}>${state.chatPending?'Добавляем…':'Добавить сообщение'} ${icon('arrow')}</button></form></section>`;
}

function hasIntake(key) {
    return new Date(key + 'T12:00').getDay() !== 0;
}

function medication(){const y=state.month.getFullYear(),m=state.month.getMonth(),days=new Date(y,m+1,0).getDate(),offset=(new Date(y,m,1).getDay()+6)%7,day=state.selectedDay,taken=state.taken.has(day);return `${heading('Календарь приёма','Учебное расписание и ваши отметки. Здесь нельзя назначить или изменить лечение.')}<div class="content-grid"><section class="surface calendar"><div class="calendar-top"><button class="btn outline small" data-month="-1" aria-label="Предыдущий месяц">${icon('back')}</button><h2>${new Intl.DateTimeFormat('ru',{month:'long',year:'numeric'}).format(state.month)}</h2><button class="btn outline small" data-month="1" aria-label="Следующий месяц">${icon('arrow')}</button></div><div class="calendar-grid">${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(x=>`<span class="weekday">${x}</span>`).join('')}${'<span></span>'.repeat(offset)}${Array.from({length:days},(_,i)=>{const key=dateKey(new Date(y,m,i+1));return `<button class="day ${state.taken.has(key)?'taken':''} ${key===todayKey?'today':''}" data-day="${key}" aria-pressed="${key===day}" aria-label="${i+1} ${new Intl.DateTimeFormat('ru',{month:'long'}).format(state.month)}${state.taken.has(key)?', приём отмечен':''}">${i+1}</button>`;}).join('')}</div><p class="subtle" style="margin:18px 0 0">✓ — вы отметили приём · Учебные записи: понедельник–суббота</p></section><section class="surface tile"><span class="pill">${new Intl.DateTimeFormat('ru',{day:'numeric',month:'long',year:'numeric'}).format(new Date(day+'T12:00'))}</span><h2>${hasIntake(day)?'Учебный препарат':'Нет учебных приёмов'}</h2>${hasIntake(day)?`<p>09:00 · Пример расписания, без действующего вещества и дозировки.</p><p role="status">Статус: <strong>${taken?'Принял — по вашей отметке':'Не отмечен'}</strong></p><button class="btn" data-take="${day}" ${taken?'disabled':''}>${icon('check')} ${taken?'Приём отмечен':'Принял'}</button>`:'<p>На выбранный день учебные записи отсутствуют.</p>'}<p class="subtle" style="margin-top:20px">Отметка хранится до перезагрузки и не подтверждает фактический приём.</p></section></div>`;}
    const phases = ['Вдох', 'Пауза', 'Выдох', 'Пауза'];
    let breathTimer = null,
        audio = null,
        audioGain = null,
        audioToken = 0;

    function games() {
        return `${heading('Мини-игры','Небольшая добровольная пауза. Начните и завершите её в удобный момент.')}<div class="content-grid"><section class="surface tile"><span class="eyebrow">${icon('game')} Дыхание по квадрату</span><h2>Следуйте за четырьмя сторонами</h2><div class="breathing ${state.breathRunning?'running':''}" id="breathing"><div class="breath-square"><i class="breath-dot" style="animation-delay:-${state.breathSeconds}s" aria-hidden="true"></i><strong id="breathPhase">${state.breathSeconds||state.breathRunning?phases[Math.floor(state.breathSeconds/4)%4]:'Готовы?'}</strong><span id="breathCount">${state.breathRunning?4-state.breathSeconds%4+' сек.':state.breathSeconds?'На паузе':'Нажмите «Начать»'}</span></div></div><ol class="phase-list">${phases.map((p,i)=>`<li data-phase="${i}" class="${Math.floor(state.breathSeconds/4)%4===i&&state.breathRunning?'active':''}">${p}<small>4 секунды</small></li>`).join('')}</ol><div class="actions"><button class="btn" data-action="breath-toggle">${state.breathRunning?'Пауза':state.breathSeconds?'Продолжить':'Начать'}</button><button class="btn outline" data-action="breath-reset">Сбросить</button></div><p class="subtle" style="margin:20px 0 0">Демонстрационный тренажёр, без медицинского допуска. Дышите без усилия; если некомфортно, остановитесь и вернитесь к обычному дыханию.</p></section><aside class="aside-card"><div class="hero-icon">${icon('leaf')}</div><h2>Вы управляете темпом паузы</h2><p>Вдох, пауза, выдох, пауза — четыре стороны квадрата. Остановиться можно в любой момент. Упражнение не оценивает ваше состояние.</p>${external('Описание упражнения · UCLH NHS','https://www.uclh.nhs.uk/patients-and-visitors/patient-information-pages/uclh-respiratory-outpatient-physiotherapy-breathlessness')}</aside></div>`;
    }

    function films() {
        return `${heading('Кино для спокойного вечера','Истории, к которым можно обратиться в свободное время. Выбирайте по своему настроению.')}<div class="tile-grid"><article class="surface tile"><div class="film-cover"><span>Поллианна</span></div><h2>Поллианна</h2><p>История девочки, которая старается находить поводы для радости в повседневной жизни.</p><span class="pill">Семейная история</span></article><article class="surface tile"><div class="film-cover totoro"><span>Мой сосед<br>Тоторо</span></div><h2>Мой сосед Тоторо</h2><p>Две сестры знакомятся с новым домом, природой вокруг и необычными лесными соседями.</p><span class="pill">Анимация · фантазия</span></article></div><p class="subtle" style="margin-top:22px">Это подборка для досуга, без обещания лечебного эффекта. Фильмы здесь не воспроизводятся.</p>`;
    }

    function sounds() {
        return `${heading('Звуки','Создайте фон для небольшой передышки. Вы управляете воспроизведением.')}<section class="surface tile" style="max-width:760px"><div class="sound-scene">${icon('sound')}<div class="wave"></div><div class="wave"></div></div><span class="eyebrow">Океанские волны</span><h2>Побудьте у воображаемого берега</h2><p>Мягкий шум с ритмом прибоя. Звук синтезируется в браузере — это не запись природы и не радиопоток.</p><p id="audioState" role="status" class="subtle">${state.audioStatus==='playing'?'Воспроизводится':state.audioStatus==='paused'?'На паузе':state.audioStatus==='loading'?'Подготовка звука…':'Звук выключен'}</p>${state.audioError?`<p class="field-error" role="alert">${state.audioError}</p>`:''}<button class="btn" data-action="audio-toggle" ${state.audioStatus==='loading'?'disabled':''}>${icon('sound')} ${state.audioStatus==='playing'?'Пауза':state.audioStatus==='paused'?'Продолжить':'Включить волны'}</button><div class="volume-row"><label for="volume">Громкость · <span id="volumeValue">${state.volume}%</span></label><input id="volume" type="range" min="0" max="100" value="${state.volume}"></div><p class="subtle" style="margin-top:18px">При переходе в другой раздел звук остановится.</p></section>`;
    }

    function doctorList() {
        return `${heading('Мои пациенты','Только пациенты с действующей связью.')}<div class="stack">${people.length?people.map(p=>`<article class="surface tile"><div class="person">${avatar(p)}<div><strong>${escapeHtml(p.name)}</strong><small>Связанный пациент</small></div></div><div class="actions" style="margin-top:18px">${linkButton('История пациента '+icon('arrow'),'#/doctor/patients/'+p.id,'soft small')}${linkButton('Учебный чат','#/doctor/chat/'+p.id,'outline small')}</div></article>`).join(''):'<div class="surface empty"><h2>Пока нет пациентов</h2><p>Пациенты появятся после назначения связи оператором.</p></div>'}</div>`;
    }

    function doctorDetail(route) {
        const p = people.find(p => p.id === route.patientId);
        if (!p) return missingPage(route);
        return `<a class="back" href="#/doctor">К моим пациентам</a>${heading(escapeHtml(p.name),'Сохранённые наблюдения пациента.')}<section class="surface tile"><h2>Ведущий врач</h2><p>${escapeHtml(sessionUser.name)}</p><p>Назначения и клинические заключения не формируются.</p></section><div class="section-heading"><h2>Наблюдения пациента</h2></div><div class="history-list">${reportCards(p.id)}</div>${moreReports()}`;
    }

    function interactions() {
        return `${heading('Лекарственная совместимость','Внешний справочный инструмент для врача.')}<div class="content-grid"><section class="surface tile"><div class="hero-icon">${icon('pill')}</div><h2>Проверить на Drugs.com</h2><p>Проверка откроется на внешнем сайте на английском языке. Названия препаратов вводятся там самостоятельно; данные пациента не передаются.</p><a class="btn" href="https://www.drugs.com/drug_interactions.html" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Открыть проверку ${icon('external')}</a><p class="subtle" style="margin-top:20px">Автоматическая проверка внутри VeganMedTech пока не подключена. Отсутствие результата не означает совместимость.</p></section><aside class="aside-card"><h2>Решение остаётся за врачом</h2><p>Внешний справочник не заменяет действующие инструкции ГРЛС и рекомендации Минздрава РФ. Здесь не формируются назначения, отмены или изменения лечения.</p></aside></div>`;
    }

    function missingPage(route) {
        return `${heading('Страница не найдена','Вернитесь к основному разделу кабинета.')}${linkButton('Вернуться в кабинет','#/'+route.role,'soft')}`;
    }
    const qDraft = tool => state.questionnaires[tool.id] || (state.questionnaires[tool.id] = {
        answers: Array(tool.questions.length).fill(null),
        step: 0,
        started: false,
        result: null,
        showResult: false,
        causes: ['', '', ''],
        error: '',
        resetPrompt: false
    });
    const qAnswered = (tool, draft) => draft.answers.filter(value => tool.options.some(option => option[0] === value)).length;
    const qSource = tool => `<p class="q-source">${external(escapeHtml(tool.source),tool.sourceUrl)}${tool.scoringUrl?`<br>${external('Инструкция подсчёта E. Broadbent',tool.scoringUrl)}`:''}<br><span>${escapeHtml(tool.version)}</span></p>`;

    function questionnaireCatalog() {
        return `${heading('Опросники','Небольшая пауза, чтобы прислушаться к себе. Выберите, с чего начать.')}<div class="q-intro"><p>Ответы обрабатываются автоматически. Вы увидите баллы и пояснение к выбранной методике.</p><p class="subtle">Только демонстрация на вымышленных ответах. Результаты не являются диагнозом. Ответы и черновики останутся в этой вкладке до перезагрузки.</p></div><div class="q-catalog">${CompassQuestionnaires.list.map((tool,i)=>{
        const draft=state.questionnaires[tool.id],count=draft?qAnswered(tool,draft):0;
        return `<article class="surface q-card"><div class="q-card-top"><span class="q-mark" aria-hidden="true">${String(i+1).padStart(2,'0')}</span><span class="pill">${escapeHtml(tool.tag)}</span></div><h2>${escapeHtml(tool.title)}</h2><p>${escapeHtml(tool.description)}</p><p class="q-meta">${tool.questions.length} ${tool.id==='bipq'?'оценок и три причины':tool.id==='temmo'?'утверждений':tool.id==='lsia'?'утверждений':'утверждений'} · ${tool.id==='bipq'?'От 0 до 10':tool.id==='temmo'?'Шесть вариантов':tool.id==='lsia'?'Три варианта':'Да или нет'}</p><div class="q-card-bottom">${draft?.result?'<span class="q-state">Расчёт готов</span>':count?`<span class="q-state">Ответов: ${count} из ${tool.questions.length}</span>`:'<span class="subtle">Можно пройти в своём темпе</span>'}${linkButton(`${draft?.result?'Открыть результат':draft?.started?'Продолжить':'Начать'} ${icon('arrow')}`,'#/patient/questionnaires/'+tool.id,'small')}</div><details class="q-details"><summary>Источник и особенности</summary>${qSource(tool)}<p class="subtle">${escapeHtml(tool.notice)}</p></details></article>`;
      }).join('')}</div>`;
    }

    function questionnairePage(route) {
        const tool = CompassQuestionnaires.get(route.questionnaireId);
        if (!tool) return `${heading('Опросник не найден','Выберите одну из методик в каталоге.')}${linkButton('К опросникам','#/patient/questionnaires','outline')}`;
        const draft = qDraft(tool),
            count = qAnswered(tool, draft),
            back = '<a class="back" href="#/patient/questionnaires">' + icon('back') + ' Все опросники</a>';
        if (draft.showResult && draft.result) return back + questionnaireResult(tool, draft);
        const source = `<aside class="aside-card q-aside"><span class="eyebrow">О методике</span><h2>${escapeHtml(tool.short)}</h2><p>${escapeHtml(tool.notice)}</p>${qSource(tool)}<p class="subtle">Демонстрационный расчёт. Для медицинского применения требуется отдельная проверка.</p></aside>`;
        if (!draft.started) return `${back}${heading(tool.title,tool.tag)}<div class="content-grid"><section class="surface form-card q-start"><span class="pill">${tool.questions.length} ${tool.id==='bipq'?'числовых оценок':'утверждений'}</span><h2>Перед началом</h2><p>${escapeHtml(tool.instruction)}</p><p class="retention">${icon('info')}<span>Используйте вымышленные ответы. Они сохраняются только до перезагрузки этой вкладки. Можно вернуться к любому ответу.</span></p><button class="btn" data-q-action="start">Начать опрос ${icon('arrow')}</button></section>${source}</div>`;
        const causes = tool.id === 'bipq' && draft.step === tool.questions.length,
            last = draft.step === tool.questions.length - 1 && tool.id !== 'bipq',
            steps = tool.questions.length + (tool.id === 'bipq' ? 1 : 0);
        const question = causes ? `<fieldset class="q-fieldset"><legend id="qQuestion" tabindex="-1">Что, по вашему мнению, могло вызвать заболевание?</legend><p class="field-help" id="qHelp">Перечислите до трёх причин в порядке значимости. Этот шаг можно пропустить: текст не влияет на баллы. До 500 символов в каждом поле.</p>${draft.causes.map((value,i)=>`<label class="q-cause-label" for="qCause${i}">Причина ${i+1}${i===0?' · наиболее важная':''}</label><textarea id="qCause${i}" data-q-cause="${i}" rows="2" maxlength="500" aria-describedby="qHelp">${escapeHtml(value)}</textarea>`).join('')}</fieldset>` : `<fieldset class="q-fieldset" aria-describedby="qHelp${draft.error?' qError':''}"><legend id="qQuestion" tabindex="-1">${escapeHtml(tool.questions[draft.step])}</legend><p class="field-help" id="qHelp">${tool.anchors?'Выберите одно число. Ноль — полноценный ответ.':'Выберите один вариант, который вам ближе.'}</p>${tool.anchors?`<div class="q-anchors"><span><b>0</b> · ${escapeHtml(tool.anchors[draft.step][0])}</span><span><b>10</b> · ${escapeHtml(tool.anchors[draft.step][1])}</span></div>`:''}<div class="q-options ${tool.anchors?'q-numbers':''}">${tool.options.map(([value,label],i)=>`<label class="q-option"><input type="radio" name="qAnswer" value="${i}" data-q-answer="${draft.step}" ${draft.answers[draft.step]===value?'checked':''} ${draft.error?'aria-invalid="true"':''}><span>${tool.id==='temmo'?`<b class="q-option-number">${value}</b>`:''}${escapeHtml(label)}</span></label>`).join('')}</div></fieldset>`;
        return `${back}${heading(tool.title,'Можно остановиться и продолжить позже в этой вкладке.')}<div class="content-grid"><form id="questionnaireForm" class="surface form-card q-form" novalidate><div class="q-progress-head"><span>Шаг ${draft.step+1} из ${steps}</span><span id="qProgressLabel">Ответов: ${count} из ${tool.questions.length}</span></div><progress id="qProgress" value="${count}" max="${tool.questions.length}" aria-label="Количество заполненных ответов"></progress>${question}<p class="field-error" id="qError" role="alert" ${draft.error?'':'hidden'}>${escapeHtml(draft.error)}</p><div class="form-actions">${draft.step>0?'<button type="button" class="btn outline" data-q-action="back">'+icon('back')+' Назад</button>':''}<button type="submit" class="btn">${causes||last?'Рассчитать результат '+icon('check'):'Далее '+icon('arrow')}</button></div><p class="field-help">${causes?'Причины будут показаны так, как вы их ввели.':'Ответы не отправляются врачу и не меняют лечение.'}</p></form>${source}</div>`;
    }

    function questionnaireResult(tool, draft) {
        const result = draft.result,
            number = value => new Intl.NumberFormat('ru-RU', {
                maximumFractionDigits: 2
            }).format(value);
        const groups = result.groups.map(group => `<article class="surface q-result-card"><h3>${group.code?`<span class="q-factor">${escapeHtml(group.code)}</span>`:''}${escapeHtml(group.title)}</h3><p class="q-score"><strong>${group.raw}</strong><span>из ${group.max} баллов${group.min?' · диапазон '+group.min+'–'+group.max:''}</span></p>${group.frequency!==undefined?`<p class="q-frequency">Накопленная частота: <b>${number(group.frequency)}%</b></p><p class="q-category">${escapeHtml(group.level)}</p>`:''}${group.children?`<dl class="q-subscales">${group.children.map(child=>`<div><dt>${escapeHtml(child.title)}</dt><dd>${child.raw} из ${child.max}</dd></div>`).join('')}</dl>`:''}</article>`).join('');
        return `${heading('Ваш результат',tool.title)}<section class="q-result-hero"><span class="eyebrow">${result.total!==undefined?'Расчёт по методике':'Профиль самоотношения'}</span>${result.total!==undefined?`<p class="q-total"><strong>${result.total}</strong><span>из ${result.max} баллов</span></p><p class="q-range">Возможный диапазон: ${result.min}–${result.max}</p>`:'<h2>12 сторон отношения к себе</h2>'}<p>${escapeHtml(result.summary)}</p><p class="subtle">Расчёт в демонстрационной среде. Это не диагноз и не рекомендация по лечению.</p></section><div class="section-heading"><h2>${tool.id==='bipq'?'Ваши исходные оценки':'Показатели по шкалам'}</h2></div><div class="q-results">${groups}</div>${tool.id==='bipq'?`<section class="surface tile q-causes-result"><h2>Ваши предполагаемые причины</h2><ol>${draft.causes.map(value=>`<li>${value.trim()?escapeHtml(value):'<span class="subtle">Не указана</span>'}</li>`).join('')}</ol><p class="subtle">Это ваши предположения. Они показаны без анализа и не влияют на баллы.</p></section>`:''}<section class="surface tile q-result-note"><h2>Как читать этот результат</h2><p>${escapeHtml(result.note)}</p>${qSource(tool)}<p class="subtle">Последний результат доступен в этой вкладке до перезагрузки.</p></section><div class="actions q-result-actions"><button class="btn outline" data-q-action="edit">Вернуться к ответам</button><a class="btn soft" href="#/patient/questionnaires">Все опросники</a><button class="btn outline" data-q-action="reset-prompt">Начать заново</button></div>${draft.resetPrompt?`<section class="notice q-reset" role="group" aria-labelledby="qResetTitle"><h2 id="qResetTitle" tabindex="-1">Очистить ответы этого опросника?</h2><p>Черновик и последний результат будут удалены из этой вкладки.</p><div class="actions"><button class="btn" data-q-action="reset-confirm">Очистить и начать</button><button class="btn outline" data-q-action="reset-cancel">Сохранить ответы</button></div></section>`:''}`;
    }

    function focusQuestion(selector = '#qQuestion') {
        const target = document.querySelector(selector);
        setTimeout(() => {
            if (target?.isConnected) {
                target.focus({
                    preventScroll: true
                });
                target.scrollIntoView({
                    block: 'nearest',
                    behavior: 'instant'
                });
            }
        }, 0);
    }

    function submitQuestionnaire(event) {
        event.preventDefault();
        const tool = CompassQuestionnaires.get(readRoute().questionnaireId);
        if (!tool) return;
        const draft = qDraft(tool);
        draft.error = '';
        if (draft.showResult) return;
        if (draft.step < tool.questions.length && !tool.options.some(option => option[0] === draft.answers[draft.step])) {
            draft.error = 'Выберите ответ, чтобы продолжить.';
            render();
            focusQuestion('input[name="qAnswer"]');
            announce(draft.error);
            return;
        }
        const finalStep = tool.questions.length - 1 + (tool.id === 'bipq' ? 1 : 0);
        if (draft.step < finalStep) {
            draft.step++;
            render();
            focusQuestion();
            return;
        }
        const missing = draft.answers.findIndex(value => !tool.options.some(option => option[0] === value));
        if (missing >= 0) {
            draft.step = missing;
            draft.error = 'Ответьте на этот вопрос перед расчётом результата.';
            render();
            focusQuestion('input[name="qAnswer"]');
            return;
        }
        try {
            draft.result = CompassQuestionnaires.score(tool.id, draft.answers);
            draft.showResult = true;
            render(true);
            focusQuestion('#pageTitle');
            window.scrollTo({
                top: 0,
                behavior: 'instant'
            });
            announce('Расчёт готов. Результат доступен до перезагрузки.');
        } catch (error) {
            draft.error = 'Не удалось рассчитать результат. Ответы сохранены; попробуйте ещё раз.';
            render();
            focusQuestion('#questionnaireForm button[type="submit"]');
            announce(draft.error);
        }
    }

    function questionnaireAction(action) {
        const tool = CompassQuestionnaires.get(readRoute().questionnaireId);
        if (!tool) return;
        const draft = qDraft(tool);
        draft.error = '';
        if (action === 'start') {
            draft.started = true;
            render();
            focusQuestion();
        }
        if (action === 'back') {
            draft.step = Math.max(0, draft.step - 1);
            render();
            focusQuestion();
        }
        if (action === 'edit') {
            draft.showResult = false;
            draft.resetPrompt = false;
            draft.step = 0;
            render();
            focusQuestion();
        }
        if (action === 'reset-prompt') {
            draft.resetPrompt = true;
            render();
            focusQuestion('#qResetTitle');
        }
        if (action === 'reset-cancel') {
            draft.resetPrompt = false;
            render();
            focusQuestion('[data-q-action="reset-prompt"]');
        }
        if (action === 'reset-confirm') {
            delete state.questionnaires[tool.id];
            qDraft(tool).started = true;
            render();
            focusQuestion();
            announce('Ответы этого опросника очищены.');
        }
    }

    function renderCabinet(focus = false) {
        const route = readRoute(),
            auth = ['welcome', 'register'].includes(route.view),
            doctor = route.role === 'doctor';
        const titles = {
            'assistant-alerts': 'Уведомления ассистента',
            welcome: 'Добро пожаловать',
            register: 'Деморегистрация',
            home: 'Главная',
            assistant: 'Ассистент',
            questionnaires: 'Опросники',
            notifications: 'Уведомления',
            doctors: 'Связаться с доктором',
            medication: 'Календарь приёма',
            games: 'Мини-игры',
            films: 'Кино для спокойного вечера',
            sounds: 'Звуки',
            report: 'Новая запись',
            history: 'История наблюдений',
            patients: 'Мои пациенты',
            detail: 'История пациента',
            chat: 'Чат',
            interactions: 'Лекарственная совместимость',
            missing: 'Страница не найдена'
        };
        const views = {
            welcome,
            register: () => registration(route),
            home: patientHome,
            assistant,
            'assistant-alerts': assistantAlertsPage,
            questionnaires: () => route.questionnaireId ? questionnairePage(route) : questionnaireCatalog(),
            notifications: notificationPage,
            doctors: doctorDirectory,
            medication,
            games,
            films,
            sounds,
            report: patientForm,
            history: patientHistory,
            patients: doctorList,
            detail: () => doctorDetail(route),
            chat: () => chatPage(route),
            interactions,
            missing: () => missingPage(route)
        };
        const content = views[route.view]();
        document.title = `${titles[route.view]} — VeganMedTech · Клинический компас`;
        const footer = '<footer class="page-footer"><span>VeganMedTech · Клинический компас</span><span>С вниманием к вашим наблюдениям</span></footer>';
        if (auth) document.querySelector('#app').innerHTML = `<div class="auth"><header class="auth-header">${brand()}<span class="pill">Демонстрация</span></header><main id="mainContent" class="auth-main" tabindex="-1">${content}</main>${footer}</div>`;
        else {
            const user = {
                name: state.profiles[route.role],
                initials: state.profiles[route.role].trim().slice(0, 2).toUpperCase()
            };
            document.querySelector('#app').innerHTML = `<aside class="sidebar">${brand('#/'+route.role)}<div class="nav-label">${doctor?'Рабочее пространство':'Личный кабинет'}</div><nav class="desktop-nav" aria-label="${doctor?'Кабинет врача':'Кабинет пациента'}">${navLinks(route)}</nav><div class="sidebar-footer"><div class="sidebar-profile">${avatar(user)}<div><strong>${escapeHtml(user.name)}</strong><small>${doctor?'Врач':'Пациент'} · аккаунт</small></div></div><button class="btn outline small logout" data-action="logout">Выйти</button></div></aside><div class="workspace"><header class="mobile-header">${brand('#/'+route.role)}${avatar(user)}<details class="mobile-menu"><summary>${titles[route.view]} · Все разделы</summary><nav aria-label="Мобильная навигация">${navLinks(route)}<button class="btn outline small logout" data-action="logout">Выйти</button></nav></details></header><div class="topbar"><div class="breadcrumb">${doctor?'Кабинет врача':'Личный кабинет'}<span>/</span>${titles[route.view]}</div><span class="today">${icon('history')}${new Intl.DateTimeFormat('ru',{day:'numeric',month:'long',year:'numeric'}).format(new Date())}</span></div><main class="main" id="mainContent" tabindex="-1"><div class="environment">${icon('info')}<span><b>Пилот: только вымышленные данные.</b> Аккаунты, самоотчёты и ИИ-чат — на сервере; учебные разделы — в памяти вкладки.</span></div><div class="screen-enter">${content}</div>${footer}</main></div>`;
        }
        if (focus) document.querySelector('#pageTitle')?.focus({
            preventScroll: true
        });
    }

    function reportCards(patientId, recent = false) {
        const reports = reportsFor(patientId);
        if (!reports.length) return emptyHistory(patientId === selfId() && readRoute().role === 'patient');
        return reports.slice(0, recent ? 2 : reports.length).map(report => `<article class="surface report-card"><div class="entry-top">${icon('history')}<time datetime="${escapeHtml(report.observedAt)}">${prettyDate(report.observedAt)}</time></div><p>${escapeHtml(report.text)}</p></article>`).join('');
    }

    function emptyHistory(patient) {
        return `<div class="surface empty"><div class="hero-icon">${icon('history')}</div><h2>Пока нет записей</h2><p>${patient ? 'Начните с небольшого наблюдения о своём дне. Позже вы сможете вернуться к нему в истории.' : 'Пациент пока не добавил наблюдения о своём состоянии.'}</p>${patient ? linkButton('Добавить первую запись', '#/patient/report', 'soft') : ''}</div>`;
    }

    function patientHistory() {
        return `${heading('История наблюдений', 'Ваши слова о вашем состоянии — без оценок и интерпретаций.', linkButton(`Новая запись ${icon('edit')}`, '#/patient/report'))}
        ${state.saved ? `<div class="notice" role="status"><strong>Запись добавлена</strong>Она появилась в вашей истории наблюдений.</div>` : ''}
        <div class="history-intro">${icon('clock')}<span>Последние наблюдения — сверху</span><span class="overview-count">${reportCount(reportsFor(selfId()).length)}</span></div>
        <div class="history-list">${reportCards(selfId())}</div>${moreReports()}`;
    }

    function patientForm() {
        return `${heading('Новая запись', 'Запишите то, что хочется сохранить и обсудить на встрече с врачом.')}
        <div class="content-grid"><form id="reportForm" class="surface form-card" novalidate aria-busy="${state.pending}">
          <label for="observedAt">Когда вы это заметили?</label>
          <input id="observedAt" name="observedAt" type="datetime-local" required value="${escapeHtml(state.draft.date)}" aria-invalid="${!!state.errors.date}" aria-describedby="dateHelp${state.errors.date ? ' dateError' : ''}" ${state.pending ? 'disabled' : ''}>
          ${state.errors.date ? `<p class="field-error" id="dateError">${state.errors.date}</p>` : ''}
          <p class="field-help" id="dateHelp">Дата и время наблюдения по часам вашего устройства.</p>
          <label for="reportText">Ваши наблюдения</label>
          <textarea id="reportText" name="text" rows="7" required placeholder="Например: как прошёл день, что изменилось в самочувствии или что хочется обсудить…" aria-invalid="${!!state.errors.text}" aria-describedby="textHelp textCount${state.errors.text ? ' textError' : ''}" ${state.pending ? 'disabled' : ''}>${escapeHtml(state.draft.text)}</textarea>
          ${state.errors.text ? `<p class="field-error" id="textError">${state.errors.text}</p>` : ''}
          <div class="form-meta"><span id="textHelp">От 1 до 2000 символов</span><span id="textCount">${state.draft.text.trim().length} / 2000</span></div>
          ${state.saveError ? `<div class="notice error" role="alert"><strong>Не удалось добавить запись</strong>${escapeHtml(state.saveMessage || 'Ваш текст остался в форме. Попробуйте ещё раз.')}</div>` : ''}
          <p class="retention">${icon('info')}<span>Запись сохраняется на сервере и доступна вашему ведущему врачу после назначения связи.</span></p>
          <div class="form-actions"><button type="submit" class="btn" ${state.pending ? 'disabled' : ''}>${state.pending ? '<span class="spinner" aria-hidden="true"></span> Добавляем…' : `${state.saveError ? 'Повторить' : 'Сохранить запись'} ${icon('check')}`}</button><a href="#/patient" class="btn outline">На главную</a></div>
        </form><aside class="aside-card"><div class="hero-icon">${icon('leaf')}</div><h2>Можно своими словами</h2><p>Здесь нет правильных или неправильных ответов. Достаточно записать то, что кажется вам важным сегодня.</p></aside></div>`;
    }

    function sendChat(event) {
        event.preventDefault();
        if (state.chatPending) return;
        const owner = sessionUser?.id,
            route = readRoute(),
            key = chatKey(route),
            text = document.querySelector('#chatText').value.trim();
        state.chatDrafts[key] = document.querySelector('#chatText').value;
        if (!text || text.length > 2000) {
            state.chatError = 'Напишите сообщение от 1 до 2000 символов.';
            render();
            document.querySelector('#chatText').focus();
            return;
        }
        state.chatPending = true;
        state.chatError = '';
        render();
        Promise.resolve().then(() => {
            if (owner !== sessionUser?.id) return;
            (state.messages[key] || (state.messages[key] = [])).push({
                from: route.role,
                text,
                time: new Intl.DateTimeFormat('ru', {
                    hour: '2-digit',
                    minute: '2-digit'
                }).format(new Date())
            });
            state.chatDrafts[key] = '';
            state.chatPending = false;
            if (readRoute().view === 'chat' && chatKey(readRoute()) === key) {
                render();
                document.querySelector('#chatText').focus();
            }
            announce('Сообщение добавлено в этой вкладке.');
        }).catch(() => {
            state.chatPending = false;
            state.chatError = 'Не удалось добавить сообщение. Черновик сохранён; попробуйте ещё раз.';
            if (readRoute().view === 'chat') render();
        });
    }

    function stopBreath() {
        clearInterval(breathTimer);
        breathTimer = null;
        state.breathRunning = false;
    }

    function updateBreath() {
        const phase = Math.floor(state.breathSeconds / 4) % 4;
        document.querySelector('#breathPhase').textContent = phases[phase];
        document.querySelector('#breathCount').textContent = 4 - state.breathSeconds % 4 + ' сек.';
        document.querySelectorAll('[data-phase]').forEach((el, i) => el.classList.toggle('active', i === phase));
        if (state.breathSeconds % 4 === 0) announce(phases[phase]);
    }

    function toggleBreath() {
        if (state.breathRunning) stopBreath();
        else {
            state.breathRunning = true;
            breathTimer = setInterval(() => {
                state.breathSeconds++;
                if (readRoute().view === 'games') updateBreath();
                else stopBreath();
            }, 1000);
        }
        render();
    }

    function stopAudio() {
        audioToken++;
        const previous = audio;
        audio = null;
        audioGain = null;
        state.audioStatus = 'stopped';
        if (previous && previous.state !== 'closed') previous.close().catch(() => {});
    }
    async function toggleAudio() {
        if (state.audioStatus === 'loading') return;
        const token = ++audioToken;
        state.audioStatus = 'loading';
        state.audioError = '';
        render();
        try {
            if (!audio) {
                const AudioCtor = window.AudioContext || window.webkitAudioContext;
                if (!AudioCtor) throw new Error('unsupported');
                audio = new AudioCtor();
                const count = audio.sampleRate * 8,
                    buffer = audio.createBuffer(2, count, audio.sampleRate);
                for (let ch = 0; ch < 2; ch++) {
                    const data = buffer.getChannelData(ch);
                    let last = 0;
                    for (let i = 0; i < count; i++) {
                        last = (last + .035 * (Math.random() * 2 - 1)) / 1.035;
                        const envelope = .35 + .65 * Math.pow(Math.sin(Math.PI * i / count), 2);
                        data[i] = last * 5 * envelope;
                    }
                }
                const source = audio.createBufferSource();
                source.buffer = buffer;
                source.loop = true;
                const filter = audio.createBiquadFilter();
                filter.type = 'lowpass';
                filter.frequency.value = 1100;
                audioGain = audio.createGain();
                audioGain.gain.value = state.volume / 100;
                source.connect(filter).connect(audioGain).connect(audio.destination);
                source.start();
                await audio.resume();
                if (token !== audioToken || readRoute().view !== 'sounds') return;
                state.audioStatus = 'playing';
            } else if (audio.state === 'running') {
                await audio.suspend();
                if (token !== audioToken) return;
                state.audioStatus = 'paused';
            } else {
                await audio.resume();
                if (token !== audioToken) return;
                state.audioStatus = 'playing';
            }
            if (readRoute().view === 'sounds') {
                render();
                document.querySelector('[data-action="audio-toggle"]')?.focus();
            }
        } catch (error) {
            if (token !== audioToken) return;
            stopAudio();
            state.audioError = 'Звук недоступен. Проверьте поддержку аудио в браузере и попробуйте ещё раз.';
            if (readRoute().view === 'sounds') render();
        }
    }
    document.addEventListener('submit', event => {
        if (event.target.id === 'reportForm') saveReport(event);
        if (event.target.id === 'chatForm') sendChat(event);
        if (event.target.id === 'assistantForm') sendAssistant(event);
        if (event.target.id === 'questionnaireForm') submitQuestionnaire(event);
    });
    document.addEventListener('input', event => {
        const el = event.target;
        if (el.matches('[data-q-answer]')) {
            const tool = CompassQuestionnaires.get(readRoute().questionnaireId);
            if (tool) {
                const draft = qDraft(tool);
                draft.answers[Number(el.dataset.qAnswer)] = tool.options[Number(el.value)][0];
                draft.result = null;
                draft.showResult = false;
                draft.error = '';
                document.querySelector('#qProgress').value = qAnswered(tool, draft);
                document.querySelector('#qProgressLabel').textContent = 'Ответов: ' + qAnswered(tool, draft) + ' из ' + tool.questions.length;
                document.querySelector('#qError').hidden = true;
                document.querySelectorAll('[name="qAnswer"]').forEach(input => input.removeAttribute('aria-invalid'));
            }
        }
        if (el.matches('[data-q-cause]')) {
            const tool = CompassQuestionnaires.get(readRoute().questionnaireId);
            if (tool) {
                const draft = qDraft(tool);
                draft.causes[Number(el.dataset.qCause)] = el.value.slice(0, 500);
                draft.result = null;
            }
        }
        if (el.id === 'reportText') {
            state.draft.text = el.value;
            document.querySelector('#textCount').textContent = `${el.value.trim().length} / 2000`;
        }
        if (el.id === 'observedAt') state.draft.date = el.value;
        if (el.id === 'profileName') state.registration[readRoute().role] = el.value;
        if (el.id === 'assistantText') state.assistant.draft=el.value;
        if (el.id === 'chatText') state.chatDrafts[chatKey(readRoute())] = el.value;
        if (el.id === 'volume') {
            state.volume = Number(el.value);
            if (audioGain) audioGain.gain.setTargetAtTime(state.volume / 100, audio.currentTime, .05);
            document.querySelector('#volumeValue').textContent = state.volume + '%';
        }
    });
    document.addEventListener('click', event => {
        const el = event.target.closest('button');
        if (!el) return;
        if (el.hasAttribute('data-assistant-more')) moreAssistant(el);
        if (el.dataset.assistantRetry) {const m=state.assistant.items.find(x=>x.id===Number(el.dataset.assistantRetry));if(m&&!state.assistant.pending){state.assistant.draft=m.text;state.assistant.key=null;sendAssistant();}}
        if (el.hasAttribute('data-alert-refresh')) refreshAssistantAlerts();
        if (el.hasAttribute('data-alert-more')) refreshAssistantAlerts(true);
        if (el.dataset.alertSeen) markAssistantAlert(el.dataset.alertSeen);
        const action = el.dataset.action;
        if (action === 'logout') logout();
        if (el.dataset.mood) {
            state.mood = el.dataset.mood;
            render();
            document.querySelector(`[data-mood="${state.mood}"]`).focus();
            announce('Настроение отмечено: ' + state.mood);
        }
        if (el.dataset.qAction) questionnaireAction(el.dataset.qAction);
        if (el.dataset.read) {
            state.read.add(el.dataset.read);
            render();
            document.querySelector('#pageTitle').focus();
            announce('Уведомление отмечено прочитанным.');
        }
        if (el.dataset.day) {
            state.selectedDay = el.dataset.day;
            render();
            document.querySelector(`[data-day="${state.selectedDay}"]`).focus();
        }
        if (el.dataset.month) {
            state.month = new Date(state.month.getFullYear(), state.month.getMonth() + Number(el.dataset.month), 1);
            render();
            document.querySelector(`[data-month="${el.dataset.month}"]`).focus();
        }
        if (el.dataset.take && !state.taken.has(el.dataset.take)) {
            state.taken.add(el.dataset.take);
            render();
            document.querySelector('#pageTitle').focus();
            announce('Приём отмечен по вашему самоотчёту.');
        }
        if (action === 'breath-toggle') {
            toggleBreath();
            document.querySelector('[data-action="breath-toggle"]').focus();
        }
        if (action === 'breath-reset') {
            stopBreath();
            state.breathSeconds = 0;
            render();
            document.querySelector('[data-action="breath-reset"]').focus();
        }
        if (action === 'audio-toggle') toggleAudio();
    });
    document.querySelector('[data-skip]').addEventListener('click', event => {
        event.preventDefault();
        document.querySelector('#mainContent').focus();
    });
    window.addEventListener('hashchange', () => {
        if (readRoute().view !== 'games') stopBreath();
        if (readRoute().view !== 'sounds') stopAudio();
        state.chatError = '';
        state.saved = readRoute().view === 'history' && state.saved;
        authError = '';
        loadRoute(true);
        window.scrollTo({
            top: 0,
            behavior: 'instant'
        });
    });
    window.addEventListener('pagehide', () => {
        stopBreath();
        stopAudio();
        stopAssistantPolling();
    });


    // Server integration: all account-specific local state belongs to a single session.
    let sessionUser = null,
        routeToken = 0,
        loading = true,
        routeTransition = false,
        renderedRoute = null,
        routeError = '',
        nextCursor = null;
    let reportKey = null,
        reportPayload = null,
        authBusy = false,
        authNotice = '',
        authError = '';
    const initialState = structuredClone(state);
    const authDraft = {
        email: '',
        name: ''
    };
    const selfId = () => sessionUser?.id;
    const publicViews = new Set(['welcome', 'register', 'login', 'password-request', 'password-reset', 'verify-email']);
    const sessionEntryViews = new Set(['welcome', 'register', 'login']);

    function resetLocal() {
        CompassAPI.clear();
        stopBreath();
        stopAudio();
        stopAssistantPolling();
        Object.assign(state, structuredClone(initialState));
        people = [];
        nextCursor = null;
        reportKey = reportPayload = null;
        authDraft.email = authDraft.name = '';
        authNotice = authError = '';
    }

    function applyUser(user) {
        if (sessionUser?.id !== user?.id) {
            resetLocal();
            routeTransition = false;
            renderedRoute = null;
        }
        sessionUser = user;
        if (user) state.profiles[user.role] = user.name;
        // Do not retain another account's DOM while its next data request runs.
        if (loading && !routeTransition && document.querySelector('#routeStatus')) render();
    }

    function authShell(content) {
        renderedRoute = null;
        routeTransition = false;
        document.title = 'VeganMedTech · Клинический компас';
        document.querySelector('#app').innerHTML = `<div class="auth"><header class="auth-header">${brand()}<span class="pill">Пилот · вымышленные данные</span></header><main id="mainContent" class="auth-main" tabindex="-1">${content}</main><footer class="page-footer">VeganMedTech · Клинический компас</footer></div>`;
    }

    function moreReports() {
        return nextCursor ? '<p><button class="btn outline" data-more-reports>Загрузить ещё</button></p>' : '';
    }

    function currentAccount() {
        return `${heading('Вы уже вошли')}<section class="surface form-card"><h2 style="overflow-wrap:anywhere">${escapeHtml(sessionUser.name)}</h2><p>Роль: ${sessionUser.role === 'doctor' ? 'Врач' : 'Пациент'}</p><div class="actions">${linkButton('Перейти в кабинет', '#/' + sessionUser.role)}<button class="btn outline" data-action="logout">Войти в другой аккаунт</button></div></section>`;
    }

    function accountForm(mode, route = readRoute()) {
        const signup = mode === 'signup',
            request = mode === 'request',
            verify = mode === 'verify',
            change = mode === 'change',
            reset = mode === 'reset';
        const title = signup ? (route.role === 'doctor' ? 'Заявка врача' : 'Регистрация пациента') : request ? 'Восстановить пароль' : verify ? 'Подтвердить почту' : change ? 'Сменить пароль' : reset ? 'Новый пароль' : 'Войти в аккаунт';
        const emailField = `<label for="accountEmail">Email</label><input id="accountEmail" name="email" type="email" autocomplete="email" required maxlength="254" value="${escapeHtml(authDraft.email)}">`;
        const passwordField = (label, name, auto) => `<label for="${name}">${label}</label><input id="${name}" name="${name}" type="password" autocomplete="${auto}" required ${name === 'current_password' || mode === 'login' ? '' : 'minlength="12"'}>`;
        return `<div class="auth-form"><a class="back" href="#/">К началу</a>${heading(title)}<form id="accountForm" data-mode="${mode}" class="surface form-card" aria-busy="${authBusy}">
    ${signup ? `<label for="profileName">Имя или псевдоним</label><input id="profileName" name="display_name" required maxlength="60" autocomplete="nickname" value="${escapeHtml(authDraft.name)}">` : ''}
    ${signup || request || mode === 'login' ? emailField : ''}
    ${change ? passwordField('Текущий пароль', 'current_password', 'current-password') : ''}
    ${!request && !verify ? passwordField(change ? 'Новый пароль' : 'Пароль', 'password', mode === 'login' ? 'current-password' : 'new-password') : ''}
    ${signup || reset || change ? passwordField('Повторите пароль', 'password_repeat', 'new-password') + '<p class="field-help">Не менее 12 символов. Используйте уникальный пароль.</p>' : ''}
    ${signup && route.role === 'doctor' ? '<p class="notice">После подтверждения почты заявка ожидает одобрения оператора. Доступ к пациентам появится только после отдельного назначения связи.</p>' : ''}
    ${authError ? `<p class="notice error auth-message" role="alert">${escapeHtml(authError)}</p>` : ''}
    ${authNotice ? `<p class="notice auth-message" role="status">${escapeHtml(authNotice)}</p>` : ''}
    <button class="btn" type="submit" ${authBusy ? 'disabled' : ''}>${authBusy ? 'Выполняем…' : verify ? 'Подтвердить почту' : request ? 'Запросить письмо' : signup ? 'Зарегистрироваться' : reset || change ? 'Сохранить пароль' : 'Войти'}</button>
    </form><div class="auth-links"><a href="#/login">Войти</a><a href="#/password/request">Забыли пароль?</a>${sessionUser ? '<button class="btn outline small" data-action="logout">Выйти</button>' : ''}</div><p class="subtle">Локальная тестовая среда. Используйте вымышленные имя и почту.</p></div>`;
    }

    function render(focus = false) {
        const route = readRoute();
        if (loading) {
            if (routeTransition) {
                const main = document.querySelector('#mainContent');
                main.inert = true;
                main.setAttribute('aria-busy', 'true');
                if (!document.querySelector('#routeStatus')) {
                    document.querySelector('#app').insertAdjacentHTML('beforeend', '<p id="routeStatus" class="route-status" role="status">Открываем раздел…</p>');
                }
                return;
            }
            authShell(heading('Загружаем…') + '<p role="status">Проверяем сессию и получаем данные.</p>');
            return;
        }
        routeTransition = false;
        if (routeError) {
            authShell(heading('Не удалось открыть раздел') + `<p class="notice error" role="alert">${escapeHtml(routeError)}</p><button class="btn" data-api-retry>Повторить</button> <a class="btn outline" href="#/">На главную</a>${sessionUser ? '<button class="btn outline" data-action="logout">Выйти</button>' : ''}`);
            return;
        }
        const modes = {
            'register': 'signup',
            'login': 'login',
            'password-request': 'request',
            'password-reset': 'reset',
            'verify-email': 'verify',
            'password-change': 'change'
        };
        if (!sessionUser && !publicViews.has(route.view)) {
            authShell(accountForm('login'));
            return;
        }
        if (sessionUser && sessionEntryViews.has(route.view)) {
            authShell(currentAccount());
            if (focus) document.querySelector('#pageTitle').focus();
            return;
        }
        if (modes[route.view]) {
            authShell(accountForm(modes[route.view], route));
            return;
        }
        if (!publicViews.has(route.view) && sessionUser?.role !== route.role) {
            authShell(heading('Раздел недоступен') + `<a class="btn" href="#/${sessionUser.role}">В свой кабинет</a>`);
            return;
        }
        if (sessionUser?.role === 'doctor' && !sessionUser.doctor_approved && !publicViews.has(route.view)) {
            authShell(heading('Заявка ожидает одобрения') + '<p class="notice">Почта подтверждена. Оператор должен одобрить врачебный доступ.</p><button class="btn" data-api-retry>Обновить статус</button> <button class="btn outline" data-action="logout">Выйти</button>');
            return;
        }
        renderCabinet(focus);
        renderedRoute = sessionUser && !publicViews.has(route.view) ? {
            hash: location.hash,
            role: sessionUser.role,
            userId: sessionUser.id
        } : null;
        if (sessionUser && !publicViews.has(route.view)) {
            const bar = document.querySelector('.topbar');
            if (bar) bar.insertAdjacentHTML('beforeend', '<a href="#/password/change">Сменить пароль</a>');
        }
    }

    function mapReports(items, patient) {
        return items.map(r => ({
            id: r.id,
            patientId: patient,
            observedAt: r.observed_at,
            text: r.text
        }));
    }
    let questionnaireLoad = null;
    function loadQuestionnaireModule() {
        if (window.CompassQuestionnaires) return Promise.resolve();
        if (questionnaireLoad) return questionnaireLoad;
        const script = document.createElement('script');
        script.src = '/api/questionnaires/module';
        questionnaireLoad = new Promise((resolve, reject) => {
            script.onload = () => window.CompassQuestionnaires ? resolve() : reject(new Error('Не удалось загрузить опросники. Повторите попытку.'));
            script.onerror = () => reject(new Error('Не удалось загрузить опросники. Проверьте соединение и повторите попытку.'));
            document.head.appendChild(script);
        }).finally(() => {
            script.remove();
            questionnaireLoad = null;
        });
        return questionnaireLoad;
    }
    async function loadRoute(focus = false) {
        stopAssistantPolling();
        const ticket = ++routeToken,
            route = readRoute();
        routeTransition = Boolean(renderedRoute && renderedRoute.userId === sessionUser?.id &&
            renderedRoute.role === route.role && !publicViews.has(route.view) && document.querySelector('.workspace'));
        loading = true;
        routeError = '';
        authBusy = false;
        render();
        try {
            const user = await CompassAPI.request('/api/me');
            if (ticket !== routeToken) return;
            applyUser(user);
            if (publicViews.has(route.view)) {
                loading = false;
                render(focus);
                return;
            }
            if (user.role !== route.role || user.role === 'doctor' && !user.doctor_approved) {
                state.reports = [];
                people = [];
                nextCursor = null;
                loading = false;
                render(focus);
                return;
            }
            if (user.role === 'patient' && ['home', 'history', 'report'].includes(route.view)) {
                const data = await CompassAPI.request('/api/me/self-reports');
                if (ticket !== routeToken) return;
                state.reports = mapReports(data.results, user.id);
                nextCursor = data.next_cursor;
            }
            if (user.role === 'patient' && route.view === 'assistant') {
                const data=await CompassAPI.request('/api/me/assistant/messages');
                if(ticket!==routeToken)return;
                state.assistant.mode=data.alerting_mode||'off';state.assistant.items=data.results;state.assistant.cursor=data.next_cursor;
                state.assistant.pending=data.results.some(m=>m.status==='pending');
            }
            if (user.role === 'patient' && route.view === 'questionnaires') {
                await loadQuestionnaireModule();
                if (ticket !== routeToken) return;
            }
            if (user.role === 'doctor') {
                const data = await CompassAPI.request('/api/patients');
                if (ticket !== routeToken) return;
                people = data.results.map(p => ({
                    ...p,
                    initials: p.name.slice(0, 2).toUpperCase()
                }));
                if (route.view === 'detail') {
                    state.reports = [];
                    const history = await CompassAPI.request(`/api/patients/${route.patientId}/self-reports`);
                    if (ticket !== routeToken) return;
                    state.reports = mapReports(history.results, route.patientId);
                    nextCursor = history.next_cursor;
                }
                if (route.view === 'chat' && !people.some(p => p.id === route.patientId)) throw new Error('Пациент недоступен.');
            }
            loading = false;
            render(focus);
            scheduleAssistantPolling();startAlertPolling();
            if(user.role==='doctor')refreshAssistantAlerts();
        } catch (error) {
            if (ticket !== routeToken || error.name === 'AbortError') return;
            if (error.status === 401 || error.status === 403 && !sessionUser) {
                applyUser(null);
                authNotice = 'Войдите в аккаунт с подтверждённой почтой.';
            } else {
                state.reports = [];
                people = [];
                nextCursor = null;
                routeError = error.message || 'Сервис недоступен. Попробуйте позднее.';
            }
            loading = false;
            render(focus);
        }
    }
    async function logout() {
        const ticket = ++routeToken;
        CompassAPI.clear();
        authBusy = false;
        routeTransition = false;
        loading = true;
        render();
        try {
            const response = await CompassAPI.auth('auth/session', {
                method: 'DELETE'
            });
            if (ticket !== routeToken) return;
            if (![200, 401, 410].includes(response.status)) throw new Error('Не удалось завершить сессию. Повторите выход.');
            applyUser(null);
            resetLocal();
            loading = false;
            routeError = '';
            location.hash = '/login';
            render();
        } catch (error) {
            if (ticket !== routeToken || error.name === 'AbortError') return;
            resetLocal();
            loading = false;
            routeError = 'Не удалось завершить сессию. Проверьте соединение и повторите выход.';
            render();
        }
    }
    async function handleAccount(event) {
        event.preventDefault();
        if (authBusy) return;
        const form = event.target,
            mode = form.dataset.mode,
            values = Object.fromEntries(new FormData(form)),
            route = readRoute(),
            ticket = routeToken;
        authDraft.email = values.email || authDraft.email;
        authDraft.name = values.display_name || authDraft.name;
        authError = '';
        authNotice = '';
        if (values.password_repeat !== undefined && values.password !== values.password_repeat) {
            authError = 'Пароли не совпадают.';
            render();
            return;
        }
        if (mode === 'signup' && !values.display_name.trim()) {
            authError = 'Укажите имя или псевдоним.';
            render();
            return;
        }
        authBusy = true;
        render();
        try {
            const operation = {
                signup: 'auth/signup',
                login: 'auth/login',
                request: 'auth/password/request',
                reset: 'auth/password/reset',
                change: 'account/password/change',
                verify: 'auth/email/verify'
            } [mode];
            const body = mode === 'signup' ? {
                email: values.email,
                password: values.password,
                display_name: values.display_name.trim(),
                role: route.role
            } : mode === 'login' ? {
                email: values.email,
                password: values.password
            } : mode === 'request' ? {
                email: values.email
            } : mode === 'verify' ? {
                key: route.key
            } : mode === 'change' ? {
                current_password: values.current_password,
                new_password: values.password
            } : {
                key: route.key,
                password: values.password
            };
            const response = await CompassAPI.auth(operation, {
                method: 'POST',
                body
            });
            if (ticket !== routeToken) return;
            const verification = response.data?.flows?.some(f => f.id === 'verify_email' && f.is_pending);
            // allauth 65.20 returns only {status:409} for an already authenticated browser.
            // This is a reason to check the session, never evidence of authentication itself.
            if (['login', 'signup'].includes(mode) && response.status === 409) {
                let user;
                try {
                    user = await CompassAPI.request('/api/me');
                } catch (error) {
                    if (error.name === 'AbortError') throw error;
                    throw new Error('Не удалось проверить текущую сессию. Проверьте соединение и повторите попытку.');
                }
                if (ticket !== routeToken) return;
                applyUser(user);
                render(true);
                return;
            }
            if (response.status === 429) throw new Error('Слишком много попыток. Попробуйте позднее.');
            if (response.status === 403) throw new Error('Запрос отклонён. Обновите страницу и повторите попытку.');
            if (response.status >= 500) throw new Error('Сервис или почта временно недоступны. Повторите попытку позднее.');
            if (response.error) throw new Error(typeof response.error.message === 'string' ? response.error.message : 'Не удалось выполнить запрос. Повторите попытку.');
            if (response.errors?.length) throw new Error(response.errors.map(e => e.message).join(' '));
            if (mode === 'signup' && verification) {
                authNotice = 'Если регистрация допустима, организатор пилота поможет подтвердить аккаунт. Письмо находится в почте пилота; на ваш настоящий адрес оно не отправляется.';
            } else if (['login', 'signup'].includes(mode) && response.status === 200 && response.meta?.is_authenticated) {
                authBusy = false;
                const loginTicket = routeToken + 1;
                await loadRoute();
                if (routeToken === loginTicket && sessionUser) location.hash = '/' + sessionUser.role;
                return;
            } else if (mode === 'login' && verification) {
                authNotice = 'Сначала подтвердите аккаунт с помощью организатора пилота.';
            } else if (mode === 'request' && response.status < 400) {
                authNotice = 'Если такой аккаунт существует, организатор пилота поможет восстановить пароль. Инструкции находятся в почте пилота; наружу письмо не отправляется.';
            } else if (mode === 'verify' && response.status < 400 || mode === 'verify' && response.status === 401 && !response.errors) {
                authNotice = 'Почта подтверждена. Теперь войдите в аккаунт.';
                location.hash = '/login';
            } else if (['reset', 'change'].includes(mode) && (response.status < 400 || response.status === 401 && !response.errors)) {
                applyUser(null);
                authNotice = 'Пароль изменён. Войдите с новым паролем.';
                location.hash = '/login';
            } else {
                throw new Error(['verify', 'reset'].includes(mode) ? 'Проверьте данные. Ссылка могла устареть или уже использована.' : response.status === 400 ? 'Проверьте введённые данные.' : 'Не удалось выполнить запрос. Повторите попытку.');
            }
        } catch (error) {
            if (ticket === routeToken && error.name !== 'AbortError') authError = error instanceof TypeError ? 'Не удалось выполнить запрос. Проверьте соединение и повторите попытку.' : error.message || 'Запрос не выполнен. Попробуйте снова.';
        } finally {
            if (ticket === routeToken) {
                authBusy = false;
                if (!loading) render();
            }
        }
    }
    async function saveReport(event) {
        event.preventDefault();
        if (state.pending) return;
        state.draft = {
            date: document.querySelector('#observedAt').value,
            text: document.querySelector('#reportText').value
        };
        const text = state.draft.text.trim(),
            date = state.draft.date;
        state.errors = {};
        if (!date || !Number.isFinite(new Date(date).getTime())) state.errors.date = 'Укажите корректную дату и время.';
        if (!text || text.length > 2000) state.errors.text = 'От 1 до 2000 символов.';
        if (Object.keys(state.errors).length) {
            render();
            document.querySelector('[aria-invalid="true"]')?.focus();
            return;
        }
        const payload = {
            observed_at: new Date(date).toISOString(),
            text
        };
        if (JSON.stringify(payload) !== reportPayload) {
            reportKey = crypto.randomUUID();
            reportPayload = JSON.stringify(payload);
        }
        state.pending = true;
        state.saveError = false;
        state.saveMessage = '';
        render();
        const ticket = routeToken, owner = sessionUser?.id;
        try {
            await CompassAPI.request('/api/me/self-reports', {
                method: 'POST',
                body: payload,
                headers: {
                    'Idempotency-Key': reportKey
                }
            });
            if (owner !== sessionUser?.id) return;
            state.pending = false;
            if (ticket !== routeToken) return;
            state.draft = {
                date: localDateTime(),
                text: ''
            };
            state.pending = false;
            state.saved = true;
            reportKey = reportPayload = null;
            location.hash = '/patient/history';
        } catch (error) {
            if (error.name === 'AbortError' || owner !== sessionUser?.id) return;
            state.pending = false;
            if (ticket !== routeToken) return;
            if (error.status === 401 || error.status === 403) {
                applyUser(null);
                authNotice = 'Сессия завершена. Войдите снова.';
            } else {
                state.saveError = true;
                state.saveMessage = error.status === 409 ? 'Конфликт отправки. Текст сохранён; измените запись или повторите после обновления истории.' : '';
                if (error.fields?.observed_at) state.errors.date = String(error.fields.observed_at);
                if (error.fields?.text) state.errors.text = String(error.fields.text);
            }
            render();
        }
    }
    async function loadMore(button) {
        if (!nextCursor) return;
        const ticket = routeToken,
            route = readRoute();
        button.disabled = true;
        const patient = route.role === 'patient' ? selfId() : route.patientId;
        const path = route.role === 'patient' ? '/api/me/self-reports' : `/api/patients/${patient}/self-reports`;
        try {
            const data = await CompassAPI.request(path + '?cursor=' + encodeURIComponent(nextCursor));
            if (ticket !== routeToken) return;
            const added = mapReports(data.results, patient);
            state.reports.push(...added.filter(r => !state.reports.some(old => old.id === r.id)));
            nextCursor = data.next_cursor;
            render();
        } catch (error) {
            if (ticket !== routeToken || error.name === 'AbortError') return;
            if ([401, 403, 404].includes(error.status)) {
                state.reports = [];
                people = [];
            }
            routeError = error.message;
            render();
        }
    }
    document.addEventListener('submit', event => {
        if (event.target.id === 'accountForm') handleAccount(event);
    });
    document.addEventListener('input', event => {
        if (event.target.id === 'profileName') authDraft.name = event.target.value;
        if (event.target.id === 'accountEmail') authDraft.email = event.target.value;
    });
    // A hash may change before hashchange runs. Never apply an old form to it.
    for (const type of ['click', 'submit', 'input', 'change']) {
        document.addEventListener(type, event => {
            if ((loading || renderedRoute && renderedRoute.hash !== location.hash) &&
                event.target.closest('#mainContent') && !event.target.closest('[data-action="logout"]')) {
                event.preventDefault();
                event.stopImmediatePropagation();
            }
        }, true);
    }
    document.addEventListener('click', event => {
        const button = event.target.closest('button');
        if (button?.hasAttribute('data-api-retry')) loadRoute(true);
        if (button?.hasAttribute('data-more-reports')) loadMore(button);
    });
    window.addEventListener('pageshow', event => {
        if (event.persisted) loadRoute();
    });
    patientItems.push(['account','edit','Сменить пароль','/password/change']);
    doctorItems.push(['account','edit','Сменить пароль','/password/change']);
    loadRoute();
