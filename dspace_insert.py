"""
Handles authentication, item creation, and bitstream upload
Loads configuration from config.env file.
"""

from pathlib import Path
import mimetypes
import requests
import io

from load_config import get_config


class DSpaceClient:
    def __init__(self, config_file: str | Path = "config.env"):

        # load config
        cfg = get_config(str(config_file))

        # get core REST API endpoint (e.g. http://localhost:8080/server/api)
        self.base_url = cfg["DSPACE_URL"].rstrip("/")

        # get credentials
        self.user = cfg.get("DSPACE_USER", "")
        self.password = cfg.get("DSPACE_PASS", "")

        # get collection UUID where the item should be imported
        self.collection_uuid = cfg.get("COLLECTION_UUID", "")

        # item publication and discovery status
        self.in_archive = cfg["ITEM_IN_ARCHIVE"].lower() in ("true", "1", "yes")
        self.discoverable = cfg["ITEM_DISCOVERABLE"].lower() in ("true", "1", "yes")

        # initialize session and token
        self.session = requests.Session()
        self.token = None

    def _extract_csrf(self, res: requests.Response) -> str | None:
        """Helper that extracts CSRF token."""

        # get CSRF token
        token = res.headers.get("DSPACE-XSRF-TOKEN")

        # if not in headers, fallback to cookies
        if not token:
            token = self.session.cookies.get("DSPACE-XSRF-COOKIE")
        #if not token:
            #token = res.headers.get("D-XSRF-TOKEN") or self.session.cookies.get("D-XSRF-TOKEN")

        return token

    def authenticate(self) -> bool:
        """Logs into DSpace REST API."""

        # Step 1: initialize session and obtain initial CSRF token via GET reques
        res_csrf = self.session.get(f"{self.base_url}/authn/status")
        csrf_token = self._extract_csrf(res_csrf)

        if not csrf_token:
            raise ConnectionError("Failed to obtain CSRF token from /authn/status.")

        # Step 2: Login
        login_headers = {
            "X-XSRF-TOKEN": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        res_login = self.session.post(
            f"{self.base_url}/authn/login",
            data={"user": self.user, "password": self.password},
            headers=login_headers,
        )

        if res_login.status_code != 200:
            raise ConnectionError(
                f"Login failed ({res_login.status_code}): {res_login.text}"
            )

        # Step 3: get authorization token
        auth_header = res_login.headers.get("Authorization")

        if auth_header:
            self.session.headers.update({"Authorization": auth_header})

        # Step 4: refresh CSRF token for subsequent requests
        updated_csrf = self._extract_csrf(res_login) or csrf_token
        if updated_csrf:
            self.session.headers.update({"X-XSRF-TOKEN": updated_csrf})

        return True

    def create_item(self, metadata_payload: dict, collection_uuid: str = None) -> dict:
        """
        Creates a new Item under target collection. 
        Sets inArchive, discoverable, and the full metadata structure.
        """

        # define target collection UUID
        target_collection = collection_uuid or self.collection_uuid
        if not target_collection:
            raise ValueError("Target collection UUID is missing in config.")

        url = f"{self.base_url}/core/items?owningCollection={target_collection}"

        # build payload wrapping inArchive, discoverable flags and metadata dictionary
        body = {
            "inArchive": self.in_archive,
            "discoverable": self.discoverable,
            "metadata": metadata_payload.get("metadata", metadata_payload)
        }

        # Step 1: send item creation request
        res = self.session.post(url, json=body)
        if res.status_code not in (200, 201):
            raise RuntimeError(f"Item creation failed ({res.status_code}): {res.text}")

        # Step 2: synchronize updated CSRF token from the response if issued
        new_csrf = self._extract_csrf(res)
        if new_csrf:
            self.session.headers.update({"X-XSRF-TOKEN": new_csrf})

        return res.json()

    def create_original_bundle(self, item_uuid: str) -> str:
        """
        Finds or creates the ORIGINAL bundle for the item.
        Returns the bundle UUID required for bitstream attachment.
        """

        # Step 1: check existing item bundles
        bundles_url = f"{self.base_url}/core/items/{item_uuid}/bundles"

        res = self.session.get(bundles_url)

        if res.status_code == 200:
            bundles = res.json().get("_embedded", {}).get("bundles", [])
            for b in bundles:
                if b.get("name") == "ORIGINAL":
                    return b["uuid"]

        # Step 2: create 'ORIGINAL' bundle when not found
        create_res = self.session.post(
            bundles_url,
            json={"name": "ORIGINAL", "metadata": {}}
        )

        if create_res.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create ORIGINAL bundle ({create_res.status_code}): {create_res.text}"
            )

        # Step 3: refresh CSRF token after bundle creation
        new_csrf = self._extract_csrf(create_res)
        if new_csrf:
            self.session.headers.update({"X-XSRF-TOKEN": new_csrf})

        return create_res.json()["uuid"]

    def upload_bitstream(self, bundle_uuid: str, file_obj: str | Path | io.BytesIO, filename: str = None,) -> dict:
      """Uploads a file into the bundle via multipart/form-data.

      Accepts either a file path on disk or an in-memory BytesIO stream.
      """
      # if it is in-memory buffer (BytesIO)
      if isinstance(file_obj, io.BytesIO):
        if not filename:
          raise ValueError(
              "Filename must be provided when uploading from BytesIO."
          )
        files = {"file": (filename, file_obj, "application/zip")}

      # if it is file on disk
      else:
        path = Path(file_obj)
        if not path.exists():
          raise FileNotFoundError(f"File not found: {path.resolve()}")
        filename = filename or path.name
        f = open(path, "rb")
        files = {"file": (filename, f, "application/zip")}

      url = f"{self.base_url}/core/bundles/{bundle_uuid}/bitstreams"

      headers = {}
      if "X-XSRF-TOKEN" in self.session.headers:
        headers["X-XSRF-TOKEN"] = self.session.headers["X-XSRF-TOKEN"]

      try:
        res = self.session.post(url, files=files, headers=headers)
      finally:
        if not isinstance(file_obj, io.BytesIO):
          f.close()

      if res.status_code not in (200, 201):
        raise RuntimeError(
            f"Bitstream upload failed ({res.status_code}): {res.text}"
        )

      new_csrf = self._extract_csrf(res)
      if new_csrf:
        self.session.headers.update({"X-XSRF-TOKEN": new_csrf})

      return res.json()

    def deposit(self, metadata_payload: dict, spatial_file: str | Path | io.BytesIO, filename: str = None, collection_uuid: str = None) -> dict:
        """
        1. Authenticate session
        2. Create Item with metadata
        3. Create ORIGINAL bundle
        4. Upload spatial bitstream
        """

        print("[>] Authenticating with DSpace REST API...")
        self.authenticate()
        print("[✓] Authenticated successfully.")

        print("[>] Depositing metadata item...")
        item = self.create_item(metadata_payload, collection_uuid=collection_uuid)
        item_uuid = item.get("uuid") or item.get("id")
        item_handle = item.get("handle", "pending")
        print(f"[✓] Item created (UUID: {item_uuid}, Handle: {item_handle}).")

        print("[>] Uploading spatial bitstream...")
        bundle_uuid = self.create_original_bundle(item_uuid)
        bitstream = self.upload_bitstream(bundle_uuid, spatial_file, filename=filename)
        bitstream_name = bitstream.get("name", filename or "uploaded_file")
        print(f"[✓] File '{bitstream_name}' uploaded successfully.")

        return {
            "item_uuid": item_uuid,
            "handle": item_handle,
            "bitstream_uuid": bitstream.get("uuid"),
            "item_url": f"{self.base_url}/core/items/{item_uuid}"
        }