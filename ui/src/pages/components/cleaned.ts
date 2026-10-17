import type { CleanedArtifact } from '../../api/models';
/** Compare unmodified locations within one known filesystem; legacy markers are unknown. */
export function cleanedMatches(rawPath:string,environmentId:string|null|undefined,marker:Pick<CleanedArtifact,'path'|'environment_id'>):boolean {
 if(!environmentId || marker.environment_id!==environmentId) return false;
 const path=marker.path.replace(/\/+$/,'');
 if(!path.startsWith('/')) return false;
 return rawPath===path || rawPath.startsWith(`${path}/`);
}
export function cleanedArtifact(rawPath:string,environmentId:string|null|undefined,markers:readonly CleanedArtifact[]=[]):CleanedArtifact|undefined {
 return markers.find(marker=>cleanedMatches(rawPath,environmentId,marker));
}
export function cleanedLabel(marker:CleanedArtifact):string { return `✕ ${marker.at.slice(0,10)} ${marker.bytes} bytes`; }
