// Shows <time class="local-time" datetime="..."> in the reader's own time zone, with the zone named
// ("Nov 2, 2026, 2:00 PM GMT+1"). Without scripts the server-rendered UTC text stays.
document.querySelectorAll("time.local-time[datetime]").forEach((el) => {
  const d = new Date(el.getAttribute("datetime"));
  if (isNaN(d)) return;
  el.textContent = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" }).format(d);
});
