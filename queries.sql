-- Comparison queries for the Top Media channels.
-- Each query starts with a "-- name:" line so top_media.py can run and label it.
-- Engagement rate = (likes + comments) / views. Videos with hidden likes or
-- disabled comments count as 0 for that metric.
-- Shorts are approximated as videos of 3 minutes or less.

-- name: 1. Channel overview
SELECT
    title,
    subscribers,
    total_views,
    video_count,
    CAST(1.0 * total_views / NULLIF(video_count, 0) AS INTEGER) AS lifetime_views_per_video
FROM channels
ORDER BY subscribers DESC;

-- name: 2. Upload frequency (uploads per week over the sample window)
SELECT
    c.title,
    COUNT(*)                                             AS videos_in_sample,
    DATE(MIN(v.published_at))                            AS oldest_in_sample,
    DATE(MAX(v.published_at))                            AS newest_in_sample,
    ROUND(
        COUNT(*) * 7.0
        / MAX(julianday(MAX(v.published_at)) - julianday(MIN(v.published_at)), 1),
        1
    )                                                    AS uploads_per_week
FROM videos v
JOIN channels c ON c.channel_id = v.channel_id
GROUP BY c.title
ORDER BY uploads_per_week DESC;

-- name: 3. Engagement rate by channel
SELECT
    c.title,
    COUNT(*)                                                         AS videos,
    CAST(AVG(v.views) AS INTEGER)                                              AS avg_views,
    ROUND(100.0 * SUM(COALESCE(v.likes, 0) + COALESCE(v.comments, 0))
          / NULLIF(SUM(v.views), 0), 2)                              AS engagement_rate_pct,
    ROUND(100.0 * SUM(COALESCE(v.likes, 0)) / NULLIF(SUM(v.views), 0), 2)    AS like_rate_pct,
    ROUND(100.0 * SUM(COALESCE(v.comments, 0)) / NULLIF(SUM(v.views), 0), 3) AS comment_rate_pct
FROM videos v
JOIN channels c ON c.channel_id = v.channel_id
GROUP BY c.title
ORDER BY engagement_rate_pct DESC;

-- name: 4. Shorts vs long-form mix and performance
SELECT
    c.title,
    CASE WHEN v.duration_seconds <= 180 THEN 'Shorts (<=3 min)' ELSE 'Long-form' END AS format,
    COUNT(*)                                                       AS videos,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY c.title), 1) AS pct_of_uploads,
    CAST(AVG(v.views) AS INTEGER)                                            AS avg_views,
    ROUND(100.0 * SUM(COALESCE(v.likes, 0) + COALESCE(v.comments, 0))
          / NULLIF(SUM(v.views), 0), 2)                            AS engagement_rate_pct
FROM videos v
JOIN channels c ON c.channel_id = v.channel_id
GROUP BY c.title, format
ORDER BY c.title, format;

-- name: 5. Top 3 videos per channel by views
SELECT title_channel AS channel, rank, video_title, views, published
FROM (
    SELECT
        c.title                                                   AS title_channel,
        ROW_NUMBER() OVER (PARTITION BY c.title ORDER BY v.views DESC) AS rank,
        v.title                                                   AS video_title,
        v.views,
        DATE(v.published_at)                                      AS published
    FROM videos v
    JOIN channels c ON c.channel_id = v.channel_id
)
WHERE rank <= 3
ORDER BY channel, rank;

-- name: 6. Posting day of week (UTC)
SELECT
    c.title,
    CASE CAST(strftime('%w', v.published_at) AS INTEGER)
        WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue' WHEN 3 THEN 'Wed'
        WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri' ELSE 'Sat' END       AS weekday,
    COUNT(*)                                                     AS uploads,
    CAST(AVG(v.views) AS INTEGER)                                          AS avg_views
FROM videos v
JOIN channels c ON c.channel_id = v.channel_id
GROUP BY c.title, strftime('%w', v.published_at)
ORDER BY c.title, strftime('%w', v.published_at);

-- name: 7. Reach relative to audience size (avg views as % of subscribers)
SELECT
    c.title,
    c.subscribers,
    CAST(AVG(v.views) AS INTEGER)                                          AS avg_views_recent,
    ROUND(100.0 * AVG(v.views) / NULLIF(c.subscribers, 0), 2)    AS avg_views_pct_of_subs
FROM videos v
JOIN channels c ON c.channel_id = v.channel_id
GROUP BY c.channel_id
ORDER BY avg_views_pct_of_subs DESC;
