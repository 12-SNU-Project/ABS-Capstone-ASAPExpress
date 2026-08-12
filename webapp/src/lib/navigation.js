export function ResolveExpertToolbarSection(pathname, search = "") {
  if (
    pathname.startsWith("/enterprise")
    || (pathname.startsWith("/document") && new URLSearchParams(search).has("caseId"))
  ) {
    return "/enterprise";
  }
  if (
    pathname.startsWith("/classification")
    || pathname.startsWith("/admin")
    || pathname.startsWith("/document")
  ) {
    return "/classification";
  }
  return "";
}
