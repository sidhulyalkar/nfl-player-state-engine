# Platform Access Matrix

| Platform | Implemented path | Appropriate use | Important limitation |
|---|---|---|---|
| X | Official API v2 | Athlete-authored public posts | Requires authorized bearer token and current access tier |
| Threads | Official API | Public posts where app permissions permit | Requires approved Meta app and permissions |
| Instagram | Business Discovery | Eligible public Business/Creator profiles | Not arbitrary personal or private accounts |
| TikTok | Research API | Approved qualifying research on public content | Approval and research-use restrictions apply |
| RSS | Feed parser | Official team/player/licensed feeds | Feed terms and provenance still apply |
| Public web | Static HTML | Official interviews, newsletters, public pages | robots.txt must allow; no login wall |
| Public browser | Playwright-rendered HTML | JavaScript pages served to clean unauthenticated browsers | stops on login/CAPTCHA/challenge; no cookie/session reuse |

Public-figure status does not override platform access controls. The collectors can ingest material actually delivered through public access paths. They do not make restricted delivery mechanisms public by force.

API permissions, versions, quotas, and page structures change. Verify current platform documentation before every live collection run and update connector tests when behavior changes.
