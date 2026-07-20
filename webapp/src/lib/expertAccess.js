export const EXPERT_ACCESS_CODE = "asap-dev";
export const ACCESS_MODE_STORAGE_KEY = "asap-access-mode";
export const GUEST_ACCESS_MODE = "guest";
export const EXPERT_ACCESS_MODE = "expert";

export function IsValidExpertAccessCode(accessCode) {
  return accessCode.trim() === EXPERT_ACCESS_CODE;
}

export function ResolveAccessMode(pathname, storedAccessMode) {
  if (pathname.startsWith("/consumer")) return GUEST_ACCESS_MODE;
  if (
    pathname.startsWith("/classification") ||
    pathname.startsWith("/enterprise") ||
    pathname.startsWith("/admin")
  ) {
    return EXPERT_ACCESS_MODE;
  }
  return storedAccessMode === GUEST_ACCESS_MODE ? GUEST_ACCESS_MODE : EXPERT_ACCESS_MODE;
}
