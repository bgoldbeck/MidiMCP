// Source selection is independent of the portable GM instrument used by MIDI export.
export function sourceOptions(track, patches) {
  const current = track.sampler;
  const options = [{value:"", label:"Project GM bank", selected:!current, disabled:false}];
  let found = false;
  for (const patch of patches) {
    const selected = !!current && current.patchId === patch.id && current.patchSha256 === patch.sha256;
    found ||= selected;
    options.push({value:patch.id,label:patch.name + (patch.available ? "" : " (unavailable)"),selected,disabled:!patch.available});
  }
  if (current && !found) options.push({value:"__current_unavailable__",label:`${current.patchId} (unavailable or changed)`,selected:true,disabled:true});
  return options;
}

export function samplerBinding(value, patches) {
  if (!value) return null;
  const patch = patches.find(p => p.id === value);
  if (!patch?.available || !patch.sha256) throw new Error("This sampled instrument is unavailable. Choose another sound source.");
  return {patchId:patch.id,patchSha256:patch.sha256};
}
