/** An HTTP response that the caller asked for and did not get. */
export class HttpError extends Error {
  constructor(readonly status: number) {
    super(`request failed with status ${status}`)
    this.name = 'HttpError'
  }
}
