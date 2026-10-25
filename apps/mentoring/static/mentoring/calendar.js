(() => {
    const calendar = document.querySelector("[data-events-url]");
    if (!calendar) return;

    const grid = calendar.querySelector("[data-calendar-grid]");
    const title = calendar.querySelector("[data-calendar-title]");
    const status = calendar.querySelector("[data-calendar-status]");
    const dialog = document.querySelector("[data-calendar-dialog]");
    const dialogTitle = dialog.querySelector("[data-dialog-title]");
    const dialogContent = dialog.querySelector("[data-dialog-content]");
    const canManage = calendar.dataset.canManage === "true";
    const csrfToken = document.querySelector(".calendar-csrf input[name=csrfmiddlewaretoken]")?.value || "";
    const locale = document.documentElement.lang || "fr-FR";
    let cursor = new Date();
    let view = "month";
    let events = [];
    let requestNumber = 0;

    const localDate = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const monday = (date) => {
        const result = localDate(date);
        result.setDate(result.getDate() - ((result.getDay() + 6) % 7));
        return result;
    };
    const plusDays = (date, amount) => {
        const result = new Date(date);
        result.setDate(result.getDate() + amount);
        return result;
    };
    const iso = (date) => date.toISOString();
    const dateLabel = (date, options) => new Intl.DateTimeFormat(locale, options).format(date);
    const durationMinutes = (event) => Math.max(15, (new Date(event.end) - new Date(event.start)) / 60000);

    function eventClass(event) {
        if (event.type === "availability") return "is-available";
        if (event.status === "confirmee") return "is-confirmed";
        if (event.status === "annulee") return "is-cancelled";
        if (event.status === "terminee") return "is-completed";
        return "is-pending";
    }

    function eventButton(event, compact = false) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `calendar-event ${eventClass(event)}${compact ? " is-compact" : ""}`;
        button.title = `${event.title} · ${dateLabel(new Date(event.start), { hour: "2-digit", minute: "2-digit" })}`;
        const time = document.createElement("span");
        time.className = "calendar-event-time";
        time.textContent = dateLabel(new Date(event.start), { hour: "2-digit", minute: "2-digit" });
        const name = document.createElement("span");
        name.className = "calendar-event-name";
        name.textContent = event.title;
        button.append(time, name);
        button.addEventListener("click", () => openEvent(event));
        return button;
    }

    function addAction(container, label, url, style = "outline") {
        if (!url) return;
        const link = document.createElement("a");
        link.className = `btn btn-${style}`;
        link.href = url;
        link.textContent = label;
        container.append(link);
    }

    function openEvent(event) {
        dialogTitle.textContent = event.type === "availability" ? "Période disponible" : event.title;
        dialogContent.replaceChildren();
        const details = document.createElement("dl");
        details.className = "calendar-detail-list";
        const lines = [
            ["Horaire", `${dateLabel(new Date(event.start), { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })} – ${dateLabel(new Date(event.end), { hour: "2-digit", minute: "2-digit" })}`],
            event.type === "availability" ? ["Formateur", event.trainer] : ["Statut", event.status_label],
        ];
        if (event.type === "availability") lines.push(["Durée proposée", `${event.duration} minutes`]);
        if (event.type === "session") {
            lines.push(["Formateur", event.trainer], ["Apprenant", event.learner]);
        }
        for (const [labelText, valueText] of lines) {
            const labelNode = document.createElement("dt");
            labelNode.textContent = labelText;
            const valueNode = document.createElement("dd");
            valueNode.textContent = valueText;
            details.append(labelNode, valueNode);
        }
        dialogContent.append(details);

        const actions = document.createElement("div");
        actions.className = "calendar-dialog-actions";
        if (event.type === "availability") {
            if (canManage) {
                addAction(actions, "Modifier", event.url);
                addAction(actions, "Planifier une séance", event.plan_url, "primary");
                if (!event.has_sessions) {
                    const form = document.createElement("form");
                    form.method = "post";
                    form.action = event.delete_url;
                    const token = document.createElement("input");
                    token.type = "hidden";
                    token.name = "csrfmiddlewaretoken";
                    token.value = csrfToken;
                    const button = document.createElement("button");
                    button.type = "submit";
                    button.className = "btn btn-danger-outline";
                    button.textContent = "Supprimer";
                    form.append(token, button);
                    actions.append(form);
                }
            } else {
                addAction(actions, "Choisir un créneau", event.url, "primary");
            }
        } else {
            addAction(actions, "Voir la séance", event.url, "primary");
        }
        dialogContent.append(actions);
        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "");
    }

    function renderMonth() {
        const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
        const start = monday(first);
        const end = plusDays(start, 42);
        title.textContent = dateLabel(cursor, { month: "long", year: "numeric" });
        const shell = document.createElement("div");
        shell.className = "month-calendar";
        const weekdays = document.createElement("div");
        weekdays.className = "month-weekdays";
        for (let i = 0; i < 7; i++) {
            const day = plusDays(start, i);
            const cell = document.createElement("div");
            cell.textContent = dateLabel(day, { weekday: "short" });
            weekdays.append(cell);
        }
        const days = document.createElement("div");
        days.className = "month-days";
        for (let i = 0; i < 42; i++) {
            const day = plusDays(start, i);
            const cell = document.createElement("section");
            cell.className = "month-day";
            if (day.getMonth() !== cursor.getMonth()) cell.classList.add("is-outside");
            if (localDate(day).getTime() === localDate(new Date()).getTime()) cell.classList.add("is-today");
            const number = document.createElement("span");
            number.className = "month-day-number";
            number.textContent = String(day.getDate());
            cell.append(number);
            const dayEvents = events.filter((event) => {
                const startAt = localDate(new Date(event.start)).getTime();
                const endAt = localDate(new Date(event.end)).getTime();
                const target = localDate(day).getTime();
                return startAt <= target && target <= endAt;
            });
            for (const event of dayEvents.slice(0, 3)) cell.append(eventButton(event, true));
            if (dayEvents.length > 3) {
                const more = document.createElement("span");
                more.className = "calendar-more";
                more.textContent = `+${dayEvents.length - 3} autres`;
                cell.append(more);
            }
            days.append(cell);
        }
        shell.append(weekdays, days);
        grid.replaceChildren(shell);
        return [start, end];
    }

    function renderWeek() {
        const start = monday(cursor);
        const end = plusDays(start, 7);
        const weekEnd = plusDays(end, -1);
        title.textContent = `${dateLabel(start, { day: "numeric", month: "long" })} – ${dateLabel(weekEnd, { day: "numeric", month: "long", year: "numeric" })}`;
        const shell = document.createElement("div");
        shell.className = "week-calendar";
        const corner = document.createElement("div");
        corner.className = "week-corner";
        shell.append(corner);
        for (let i = 0; i < 7; i++) {
            const day = plusDays(start, i);
            const head = document.createElement("div");
            head.className = "week-day-heading";
            if (localDate(day).getTime() === localDate(new Date()).getTime()) head.classList.add("is-today");
            const weekday = document.createElement("span");
            weekday.textContent = dateLabel(day, { weekday: "short" });
            const number = document.createElement("strong");
            number.textContent = String(day.getDate());
            head.append(weekday, number);
            shell.append(head);
        }
        const timeColumn = document.createElement("div");
        timeColumn.className = "week-time-column";
        for (let hour = 7; hour <= 21; hour++) {
            const label = document.createElement("span");
            label.textContent = `${String(hour).padStart(2, "0")}:00`;
            timeColumn.append(label);
        }
        shell.append(timeColumn);
        for (let i = 0; i < 7; i++) {
            const day = plusDays(start, i);
            const dayColumn = document.createElement("div");
            dayColumn.className = "week-day-column";
            for (let hour = 7; hour <= 21; hour++) {
                const line = document.createElement("div");
                line.className = "week-hour-line";
                dayColumn.append(line);
            }
            for (const event of events.filter((item) => localDate(new Date(item.start)).getTime() === localDate(day).getTime())) {
                const block = eventButton(event);
                const begins = new Date(event.start);
                const ends = new Date(event.end);
                const minutes = (begins.getHours() - 7) * 60 + begins.getMinutes();
                const height = durationMinutes(event);
                block.style.top = `${Math.max(0, minutes) * 1.05}px`;
                block.style.height = `${Math.max(21, height * 1.05 - 2)}px`;
                if (begins.getHours() < 7 || ends.getHours() > 22) block.classList.add("is-clipped");
                dayColumn.append(block);
            }
            shell.append(dayColumn);
        }
        grid.replaceChildren(shell);
        return [start, end];
    }

    async function render() {
        const thisRequest = ++requestNumber;
        status.textContent = "Chargement du calendrier…";
        const range = view === "month" ? renderMonth() : renderWeek();
        const url = new URL(calendar.dataset.eventsUrl, window.location.origin);
        url.searchParams.set("start", iso(range[0]));
        url.searchParams.set("end", iso(range[1]));
        if (calendar.dataset.trainerId) url.searchParams.set("formateur", calendar.dataset.trainerId);
        try {
            const response = await fetch(url, { headers: { Accept: "application/json" } });
            if (!response.ok) throw new Error("Impossible de charger les événements.");
            const payload = await response.json();
            if (thisRequest !== requestNumber) return;
            events = payload.events;
            status.textContent = events.length ? "" : "Aucun événement sur cette période.";
            if (view === "month") renderMonth();
            else renderWeek();
        } catch (error) {
            if (thisRequest !== requestNumber) return;
            status.textContent = error.message;
        }
    }

    calendar.querySelector("[data-calendar-prev]").addEventListener("click", () => {
        if (view === "month") cursor = new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1);
        else cursor = plusDays(cursor, -7);
        render();
    });
    calendar.querySelector("[data-calendar-next]").addEventListener("click", () => {
        if (view === "month") cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
        else cursor = plusDays(cursor, 7);
        render();
    });
    calendar.querySelector("[data-calendar-today]").addEventListener("click", () => { cursor = new Date(); render(); });
    calendar.querySelectorAll("[data-calendar-view]").forEach((button) => button.addEventListener("click", () => {
        view = button.dataset.calendarView;
        calendar.querySelectorAll("[data-calendar-view]").forEach((item) => item.classList.toggle("is-active", item === button));
        render();
    }));
    document.querySelector("[data-dialog-close]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    render();
})();
