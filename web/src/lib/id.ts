let counter = 0;

/** Collision-resistant id for client-created entities in the prototype. */
export function createId(prefix = 'id'): string {
  counter += 1;
  const time = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 7);
  return `${prefix}_${time}${counter.toString(36)}${rand}`;
}
