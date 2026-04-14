#single import point prevents circular imports

from app.models.osca import (
    OscaMajorGroup,
    OscaSubMajorGroup,
    OscaMinorGroup,
    OscaUnitGroup,
    OscaOccupation,
    OscaAlternativeTitle
)

from app.models.skills import (
    EscoSkill,
    OscaOccupationSkill,
    OscaOccupationSkillSnapshot
)

from app.models.jobs import (
    JobPostLog,
    JobPostSkill
)

from app.models.auth import (
    SystemRole,
    SystemPage,
    SystemRolePage,
    SystemEndUser
)

# Alias for convenience
User = SystemEndUser